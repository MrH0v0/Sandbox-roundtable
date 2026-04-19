from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QSettings, QThread, Signal

from sandbox.core.service_container import AppServices, build_services
from sandbox.desktop.workers.discussion_worker import (
    DISCUSSION_CANCELLED_MESSAGE,
    DiscussionWorker,
)
from sandbox.desktop.workers.session_query_worker import SessionQueryWorker
from sandbox.schemas.config import RoundtableConfigSummary
from sandbox.schemas.discussion import (
    DiscussionProgressEvent,
    DiscussionStage,
    ProgressEventType,
    RunDiscussionRequest,
    RunDiscussionResponse,
    SessionRecord,
    SessionSummary,
)
from sandbox.schemas.usage import TokenUsage


RESULT_SOURCE_NONE = "none"
RESULT_SOURCE_CURRENT_RUN = "current_run"
RESULT_SOURCE_HISTORY_REPLAY = "history_replay"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MemberRunState:
    member_id: str
    name: str
    model: str
    status: str = "waiting"
    stage: DiscussionStage | None = None
    error: str | None = None
    updated_at: datetime | None = None


@dataclass
class RunStateSnapshot:
    session_id: str = ""
    scenario_title: str = ""
    config_name: str = ""
    is_running: bool = False
    current_stage: DiscussionStage | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_message: str = ""
    error: str | None = None
    member_states: dict[str, MemberRunState] = field(default_factory=dict)
    completed_stages: set[DiscussionStage] = field(default_factory=set)
    events: list[DiscussionProgressEvent] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass(frozen=True)
class BusyStateSnapshot:
    bootstrapping: bool = False
    shutting_down: bool = False
    discussion_active: bool = False
    session_refresh_active: bool = False
    session_load_active: bool = False

    @property
    def any_active(self) -> bool:
        return any(
            (
                self.bootstrapping,
                self.shutting_down,
                self.discussion_active,
                self.session_refresh_active,
                self.session_load_active,
            )
        )


class DesktopState(QObject):
    configs_changed = Signal(object)
    sessions_changed = Signal(object)
    runtime_info_changed = Signal(object)
    run_state_changed = Signal(object)
    current_session_changed = Signal(object)
    replay_session_changed = Signal(object)
    results_session_changed = Signal(object, str)
    default_config_changed = Signal(str)
    api_settings_saved = Signal(bool, str)
    token_limit_saved = Signal(bool, str)
    api_connectivity_tested = Signal(object)
    error_occurred = Signal(str)
    busy_changed = Signal(object)

    def __init__(
        self,
        *,
        service_factory=build_services,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service_factory = service_factory
        self._services: AppServices = service_factory()
        self._settings = QSettings("sandbox", "roundtable-desktop")

        self.configs: list[RoundtableConfigSummary] = []
        self.sessions: list[SessionSummary] = []
        self.current_session: SessionRecord | None = None
        self.current_run_session: SessionRecord | None = None
        self.replay_session: SessionRecord | None = None
        self.results_session: SessionRecord | None = None
        self.results_source = RESULT_SOURCE_NONE
        self.run_state: RunStateSnapshot | None = None
        self.default_config_name = self._settings.value("default_config_name", "", str)

        self._worker_thread: QThread | None = None
        self._worker: DiscussionWorker | None = None

        self._session_refresh_worker: SessionQueryWorker | None = None
        self._session_load_worker: SessionQueryWorker | None = None
        self._api_test_worker: SessionQueryWorker | None = None
        self._requested_session_id: str | None = None
        self._active_session_load_id: str | None = None

        self._shutdown_in_progress = False
        self._closing_message = ""

    def bootstrap(self) -> None:
        self.refresh_configs()
        self.refresh_sessions()
        self.runtime_info_changed.emit(self._services.workbench_service.get_runtime_info())
        self.default_config_changed.emit(self.default_config_name)
        self.current_session_changed.emit(self.current_session)
        self.replay_session_changed.emit(self.replay_session)
        self.results_session_changed.emit(self.results_session, self.results_source)
        self.run_state_changed.emit(self.run_state)
        self._emit_busy_state()

    def refresh_configs(self) -> None:
        try:
            self.configs = self._services.workbench_service.list_configs()
        except Exception as exc:
            self.error_occurred.emit(f"加载配置列表失败: {exc}")
            return

        self.configs_changed.emit(self.configs)

    def refresh_runtime_info(self) -> None:
        self.runtime_info_changed.emit(self._services.workbench_service.get_runtime_info())

    def refresh_sessions(self) -> None:
        if self._shutdown_in_progress:
            return

        if self._session_refresh_worker and self._session_refresh_worker.is_running:
            return

        self._session_refresh_worker = SessionQueryWorker(
            task=self._services.workbench_service.list_sessions,
        )
        self._session_refresh_worker.finished.connect(self._handle_sessions_loaded)
        self._session_refresh_worker.failed.connect(self._handle_session_refresh_failed)
        self._session_refresh_worker.start()
        self._emit_busy_state()

    def set_default_config_name(self, config_name: str) -> None:
        self.default_config_name = config_name
        self._settings.setValue("default_config_name", config_name)
        self.default_config_changed.emit(config_name)

    def save_api_settings(self, payload: dict[str, Any]) -> bool:
        provider_label = str(payload.get("provider_label") or "").strip()
        base_url = str(payload.get("base_url") or "").strip()
        api_key = str(payload.get("api_key") or "").strip()

        if not base_url:
            self.api_settings_saved.emit(False, "接口地址不能为空。")
            return False

        try:
            runtime_info = self._services.workbench_service.save_api_settings(
                provider_label=provider_label or "自定义 OpenAI 兼容接口",
                base_url=base_url,
                api_key=api_key,
            )
        except Exception as exc:
            self.api_settings_saved.emit(False, f"保存 API 设置失败: {exc}")
            return False

        self.runtime_info_changed.emit(runtime_info)
        self.api_settings_saved.emit(True, "API 设置已保存。为确保所有链路完全一致，建议重启桌面端。")
        return True

    def save_config_token_limit(self, payload: dict[str, Any]) -> bool:
        config_name = str(payload.get("config_name") or "").strip()
        try:
            max_tokens = int(payload.get("max_tokens"))
        except (TypeError, ValueError):
            self.token_limit_saved.emit(False, "Token 上限必须是合法数字。")
            return False

        if not config_name:
            self.token_limit_saved.emit(False, "请先选择要写回的配置文件。")
            return False
        if max_tokens <= 0:
            self.token_limit_saved.emit(False, "Token 上限必须大于 0。")
            return False

        try:
            self._services.workbench_service.save_config_token_limit(
                config_name=config_name,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            self.token_limit_saved.emit(False, f"保存 token 上限失败: {exc}")
            return False

        self.refresh_configs()
        self.token_limit_saved.emit(True, "单次生成 token 上限已保存，保存后对新启动的讨论生效。")
        return True

    def add_config_member(self, payload: dict[str, Any]) -> bool:
        config_name = str(payload.get("config_name") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        model = str(payload.get("model") or "").strip()

        if not config_name:
            self.error_occurred.emit("璇峰厛閫夋嫨瑕佷慨鏀圭殑閰嶇疆鏂囦欢銆?")
            return False

        try:
            self._services.workbench_service.add_config_member(
                config_name=config_name,
                display_name=display_name,
                model=model,
            )
        except Exception as exc:
            self.error_occurred.emit(f"鏂板鎴愬憳澶辫触: {exc}")
            return False

        self.refresh_configs()
        return True

    def rename_config_member(self, payload: dict[str, Any]) -> bool:
        config_name = str(payload.get("config_name") or "").strip()
        member_id = str(payload.get("member_id") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()

        if not config_name:
            self.error_occurred.emit("璇峰厛閫夋嫨瑕佷慨鏀圭殑閰嶇疆鏂囦欢銆?")
            return False

        try:
            self._services.workbench_service.rename_config_member(
                config_name=config_name,
                member_id=member_id,
                display_name=display_name,
            )
        except Exception as exc:
            self.error_occurred.emit(f"淇敼鎴愬憳鍚嶇О澶辫触: {exc}")
            return False

        self.refresh_configs()
        return True

    def test_api_connections(self, payload: dict[str, Any]) -> bool:
        if self._api_test_worker and self._api_test_worker.is_running:
            self.api_connectivity_tested.emit(
                [{"name": "测试任务", "status": "failed", "message": "已有联通测试正在进行中。"}]
            )
            return False

        connections = payload.get("connections")
        if not isinstance(connections, list) or not connections:
            self.api_connectivity_tested.emit(
                [{"name": "测试任务", "status": "failed", "message": "请至少提供一组 API 测试配置。"}]
            )
            return False

        self._api_test_worker = SessionQueryWorker(
            task=lambda: self._services.workbench_service.test_api_connections(connections)
        )
        self._api_test_worker.finished.connect(self._handle_api_connections_tested)
        self._api_test_worker.failed.connect(self._handle_api_connections_test_failed)
        self._api_test_worker.start()
        return True

    def start_discussion(self, form_data: dict[str, Any]) -> bool:
        if self._worker_thread and self._worker_thread.isRunning():
            self.error_occurred.emit("当前已有讨论在运行，请等待本轮结束。")
            return False

        try:
            request = self._build_request(form_data)
        except Exception as exc:
            self.error_occurred.emit(f"输入校验失败: {exc}")
            return False

        self.current_session = None
        self.current_run_session = None
        self.current_session_changed.emit(None)
        self._set_results_session(None, RESULT_SOURCE_CURRENT_RUN)
        self.run_state = RunStateSnapshot(
            scenario_title=request.scenario.title,
            config_name=request.config_name,
            is_running=True,
            started_at=utc_now(),
            last_message="Discussion submitted. Initializing execution...",
        )
        self.run_state_changed.emit(self.run_state)

        self._worker_thread = QThread(self)
        self._worker = DiscussionWorker(
            service_factory=self._service_factory,
            scenario_payload=request.scenario.model_dump(mode="json"),
            config_name=request.config_name,
            member_overrides_payload=[
                override.model_dump(mode="json")
                for override in request.member_overrides
            ],
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._handle_progress)
        self._worker.finished.connect(self._handle_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.failed.connect(self._handle_failed)
        self._worker.failed.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()
        self._emit_busy_state()
        return True

    def load_session(self, session_id: str) -> bool:
        if self._shutdown_in_progress:
            return False

        self._requested_session_id = session_id
        if self._session_load_worker and self._session_load_worker.is_running:
            self._emit_busy_state()
            return True

        return self._start_session_load(session_id)

    def delete_session(self, session_id: str) -> bool:
        target_session_id = str(session_id or "").strip()
        if not target_session_id:
            self.error_occurred.emit("请选择要删除的历史 session。")
            return False

        try:
            self._services.workbench_service.delete_session(target_session_id)
        except Exception as exc:
            self.error_occurred.emit(f"删除 session 失败: {exc}")
            return False

        if self.replay_session is not None and self.replay_session.session_id == target_session_id:
            self.replay_session = None
            self.replay_session_changed.emit(None)

        if (
            self.current_session is not None
            and self.current_session.session_id == target_session_id
            and (
                self.current_run_session is None
                or self.current_run_session.session_id != target_session_id
            )
        ):
            self.current_session = None
            self.current_session_changed.emit(None)

        if (
            self.results_session is not None
            and self.results_session.session_id == target_session_id
            and self.results_source == RESULT_SOURCE_HISTORY_REPLAY
        ):
            self._set_results_session(None, RESULT_SOURCE_HISTORY_REPLAY)

        try:
            self.sessions = self._services.workbench_service.list_sessions()
        except Exception as exc:
            self.error_occurred.emit(f"刷新 session 列表失败: {exc}")
            self.sessions = [
                summary for summary in self.sessions if summary.session_id != target_session_id
            ]

        self.sessions_changed.emit(self.sessions)
        self._emit_busy_state()
        return True

    def show_current_results(self) -> bool:
        self._set_results_session(self.current_run_session, RESULT_SOURCE_CURRENT_RUN)
        return self.results_session is not None

    def show_replay_results(self) -> bool:
        if self.replay_session is None:
            self._set_results_session(None, RESULT_SOURCE_HISTORY_REPLAY)
            return False

        self._set_results_session(self.replay_session, RESULT_SOURCE_HISTORY_REPLAY)
        return True

    def shutdown(self) -> None:
        self._shutdown_in_progress = True
        self._closing_message = "Closing the workbench. Waiting for background tasks..."
        self._apply_shutdown_feedback(self._closing_message)
        self._emit_busy_state()

        if self._worker_thread and self._worker_thread.isRunning() and self._worker is not None:
            self._worker.request_cancel()

        self._wait_for_thread(
            self._worker_thread,
            timeout_ms=4000,
            progress_message="Closing the workbench. Waiting for the active discussion to stop...",
        )
        self._wait_for_thread(
            self._session_load_worker,
            timeout_ms=2500,
            progress_message="Closing the workbench. Waiting for session loading to finish...",
        )
        self._wait_for_thread(
            self._session_refresh_worker,
            timeout_ms=2500,
            progress_message="Closing the workbench. Waiting for session refresh to finish...",
        )

        try:
            asyncio.run(self._services.workbench_service.aclose())
        except Exception:
            pass
        finally:
            self._shutdown_in_progress = False
            self._emit_busy_state()

    def _handle_progress(self, event: DiscussionProgressEvent) -> None:
        if self.run_state is None:
            return

        self.run_state.events.append(event)
        self.run_state.events = self.run_state.events[-200:]
        if event.message:
            self.run_state.last_message = event.message

        if event.event_type == ProgressEventType.SESSION_STARTED:
            self.run_state.session_id = event.session_id
            for member in event.data.get("members", []):
                member_id = str(member.get("id") or "")
                if not member_id:
                    continue
                self.run_state.member_states[member_id] = MemberRunState(
                    member_id=member_id,
                    name=str(member.get("name") or member_id),
                    model=str(member.get("model") or ""),
                    status="waiting",
                )

        elif event.event_type == ProgressEventType.STAGE_STARTED:
            self.run_state.current_stage = event.stage

        elif event.event_type == ProgressEventType.MEMBER_STARTED:
            role_kind = str(event.data.get("role_kind") or "member")
            if role_kind == "system" or event.member_id is None:
                self.run_state_changed.emit(self.run_state)
                return

            member_state = self.run_state.member_states.setdefault(
                event.member_id,
                MemberRunState(
                    member_id=event.member_id,
                    name=event.member_name or event.member_id,
                    model=str(event.data.get("model") or ""),
                ),
            )
            member_state.status = "running"
            member_state.stage = event.stage
            member_state.updated_at = event.created_at
            member_state.error = None

        elif event.event_type == ProgressEventType.MEMBER_FINISHED:
            self._add_token_usage(event.data.get("token_usage"))
            role_kind = str(event.data.get("role_kind") or "member")
            if role_kind == "system" or event.member_id is None:
                self.run_state_changed.emit(self.run_state)
                return

            member_state = self.run_state.member_states.setdefault(
                event.member_id,
                MemberRunState(
                    member_id=event.member_id,
                    name=event.member_name or event.member_id,
                    model=str(event.data.get("model") or ""),
                ),
            )
            member_state.status = event.status or "success"
            member_state.stage = event.stage
            member_state.updated_at = event.created_at
            member_state.error = event.error

        elif event.event_type == ProgressEventType.STAGE_FINISHED and event.stage is not None:
            self.run_state.completed_stages.add(event.stage)

        elif event.event_type == ProgressEventType.SESSION_FINISHED:
            self.run_state.is_running = False
            self.run_state.completed_at = event.created_at

        elif event.event_type == ProgressEventType.SESSION_FAILED:
            self.run_state.is_running = False
            self.run_state.completed_at = event.created_at
            self.run_state.error = event.error

        self.run_state_changed.emit(self.run_state)

    def _handle_finished(self, response: object) -> None:
        if not isinstance(response, RunDiscussionResponse):
            self._handle_failed("Unexpected discussion response type.")
            return

        if self.run_state is not None:
            self.run_state.is_running = False
            self.run_state.completed_at = utc_now()
            self.run_state.last_message = "Discussion finished. Results are ready."
            self.run_state_changed.emit(self.run_state)

        self.current_session = response.session
        self.current_run_session = response.session
        self.current_session_changed.emit(self.current_session)
        self.show_current_results()
        self.refresh_sessions()
        self._emit_busy_state()

    def _add_token_usage(self, payload: object) -> None:
        if self.run_state is None or not isinstance(payload, dict):
            return
        usage = TokenUsage.from_payload(payload)
        if usage is None:
            return
        self.run_state.token_usage = self.run_state.token_usage.merged(usage)

    def _handle_failed(self, message: str) -> None:
        if self.run_state is not None:
            self.run_state.is_running = False
            self.run_state.error = message
            self.run_state.completed_at = utc_now()
            if self._shutdown_in_progress and message == DISCUSSION_CANCELLED_MESSAGE:
                self.run_state.last_message = "Shutdown requested. The active discussion was asked to stop."
            else:
                self.run_state.last_message = "Discussion failed."
            self.run_state_changed.emit(self.run_state)

        if not self._shutdown_in_progress:
            self.error_occurred.emit(f"讨论执行失败: {message}")

        self._emit_busy_state()

    def _handle_sessions_loaded(self, sessions: object) -> None:
        self.sessions = list(sessions) if isinstance(sessions, list) else []
        self.sessions_changed.emit(self.sessions)
        self._cleanup_session_refresh_worker()
        self._emit_busy_state()

    def _handle_session_refresh_failed(self, message: str) -> None:
        if not self._shutdown_in_progress:
            self.error_occurred.emit(f"加载 session 列表失败: {message}")
        self._cleanup_session_refresh_worker()
        self._emit_busy_state()

    def _handle_session_loaded(self, response: object) -> None:
        if not isinstance(response, RunDiscussionResponse):
            self._handle_session_load_failed("Unexpected session response type.")
            return

        requested_session_id = self._requested_session_id or response.session.session_id
        if response.session.session_id != requested_session_id:
            self._cleanup_session_load_worker(emit_busy=False)
            self._start_session_load(requested_session_id)
            return

        self.current_session = response.session
        self.current_session_changed.emit(self.current_session)
        self.replay_session = response.session
        self.replay_session_changed.emit(self.replay_session)
        self._cleanup_session_load_worker()
        self._emit_busy_state()

    def _handle_session_load_failed(self, message: str) -> None:
        if self._requested_session_id and self._requested_session_id != self._active_session_load_id:
            next_session_id = self._requested_session_id
            self._cleanup_session_load_worker(emit_busy=False)
            self._start_session_load(next_session_id)
            return

        if not self._shutdown_in_progress:
            self.error_occurred.emit(f"读取 session 失败: {message}")
        self._cleanup_session_load_worker()
        self._emit_busy_state()

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
        self._worker = None
        self._worker_thread = None
        self._emit_busy_state()

    def _cleanup_session_refresh_worker(self) -> None:
        if self._session_refresh_worker is not None:
            self._session_refresh_worker.deleteLater()
        self._session_refresh_worker = None
        self._emit_busy_state()

    def _cleanup_session_load_worker(self, *, emit_busy: bool = True) -> None:
        if self._session_load_worker is not None:
            self._session_load_worker.deleteLater()
        self._session_load_worker = None
        self._active_session_load_id = None
        if emit_busy:
            self._emit_busy_state()

    def _cleanup_api_test_worker(self) -> None:
        if self._api_test_worker is not None:
            self._api_test_worker.deleteLater()
        self._api_test_worker = None

    def _start_session_load(self, session_id: str) -> bool:
        self._active_session_load_id = session_id
        self._session_load_worker = SessionQueryWorker(
            task=lambda current_session_id=session_id: self._services.workbench_service.load_session(
                current_session_id
            ),
        )
        self._session_load_worker.finished.connect(self._handle_session_loaded)
        self._session_load_worker.failed.connect(self._handle_session_load_failed)
        self._session_load_worker.start()
        self._emit_busy_state()
        return True

    def _handle_api_connections_tested(self, results: object) -> None:
        payload = list(results) if isinstance(results, list) else []
        self.api_connectivity_tested.emit(payload)
        self._cleanup_api_test_worker()

    def _handle_api_connections_test_failed(self, message: str) -> None:
        self.api_connectivity_tested.emit(
            [{"name": "测试任务", "status": "failed", "message": message}]
        )
        self._cleanup_api_test_worker()

    def _wait_for_thread(
        self,
        worker: SessionQueryWorker | QThread | None,
        *,
        timeout_ms: int,
        progress_message: str,
    ) -> None:
        if worker is None:
            return

        self._apply_shutdown_feedback(progress_message)
        deadline = time.monotonic() + (timeout_ms / 1000)
        if isinstance(worker, QThread):
            worker.quit()

        while self._worker_is_running(worker) and time.monotonic() < deadline:
            if isinstance(worker, QThread):
                worker.wait(50)
            else:
                worker.wait(0.05)
            QCoreApplication.processEvents()

        if self._worker_is_running(worker):
            self._apply_shutdown_feedback(
                "Closing is still waiting on a background task. The app may take a little longer to exit."
            )

    def _apply_shutdown_feedback(self, message: str) -> None:
        self._closing_message = message
        if self.run_state is None:
            self.run_state = RunStateSnapshot(
                is_running=False,
                started_at=utc_now(),
                last_message=message,
            )
        else:
            self.run_state.last_message = message
        self.run_state_changed.emit(self.run_state)

    def _set_results_session(self, session: SessionRecord | None, source: str) -> None:
        self.results_session = session
        self.results_source = source
        self.results_session_changed.emit(self.results_session, self.results_source)

    def _emit_busy_state(self) -> None:
        busy_state = BusyStateSnapshot(
            bootstrapping=bool(
                self._session_refresh_worker and self._session_refresh_worker.is_running and not self.sessions
            ),
            shutting_down=bool(self._shutdown_in_progress),
            discussion_active=bool(self._worker_thread and self._worker_thread.isRunning()),
            session_refresh_active=bool(self._session_refresh_worker and self._session_refresh_worker.is_running),
            session_load_active=bool(self._session_load_worker and self._session_load_worker.is_running),
        )
        self.busy_changed.emit(busy_state)

    @staticmethod
    def _worker_is_running(worker: SessionQueryWorker | QThread | None) -> bool:
        if worker is None:
            return False
        if isinstance(worker, QThread):
            return worker.isRunning()
        return worker.is_running

    @staticmethod
    def _build_request(form_data: dict[str, Any]) -> RunDiscussionRequest:
        scenario_payload = {
            "title": str(form_data.get("title") or "").strip(),
            "background": str(form_data.get("background") or "").strip(),
            "constraints": DesktopState._split_lines(form_data.get("constraints")),
            "friendly_forces": DesktopState._split_lines(form_data.get("friendly_forces")),
            "enemy_forces": DesktopState._split_lines(form_data.get("enemy_forces")),
            "objectives": DesktopState._split_lines(form_data.get("objectives")),
            "victory_conditions": DesktopState._split_lines(form_data.get("victory_conditions")),
            "additional_notes": DesktopState._split_lines(form_data.get("additional_notes")),
        }
        payload = {
            "config_name": str(form_data.get("config_name") or "").strip(),
            "scenario": scenario_payload,
            "member_overrides": form_data.get("member_overrides") or [],
        }
        return RunDiscussionRequest.model_validate(payload)

    @staticmethod
    def _split_lines(value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        lines: list[str] = []
        for raw_line in str(value).splitlines():
            cleaned = raw_line.strip().lstrip("-").strip()
            if cleaned:
                lines.append(cleaned)
        return lines
