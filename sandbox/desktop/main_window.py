from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.pages.new_discussion_page import NewDiscussionPage
from sandbox.desktop.pages.replay_page import ReplayPage
from sandbox.desktop.pages.results_page import ResultsPage
from sandbox.desktop.pages.settings_page import SettingsPage
from sandbox.desktop.pages.status_page import StatusPage
from sandbox.desktop.state import (
    BusyStateSnapshot,
    RESULT_SOURCE_CURRENT_RUN,
    RESULT_SOURCE_HISTORY_REPLAY,
    DesktopState,
    RunStateSnapshot,
)
from sandbox.desktop.theme import (
    apply_theme,
    available_themes,
    get_status_text,
    get_status_tone,
    load_theme_key,
    normalize_status,
    save_theme_key,
)
from sandbox.desktop.widgets.common import AnimatedStackedWidget, AppComboBox, NavButton, StatusPill
from sandbox.schemas.discussion import DiscussionProgressEvent, ProgressEventType, SessionRecord


BASE_WINDOW_TITLE = "沙盘圆桌工作台"

PAGE_META = {
    "new": "新建沙盘",
    "status": "运行状态",
    "results": "结果查看",
    "replay": "Session 回放",
    "settings": "设置",
}


class MainWindow(QMainWindow):
    def __init__(self, state: DesktopState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state

        self._current_page_key = "new"
        self._results_source = RESULT_SOURCE_CURRENT_RUN
        self._results_session: SessionRecord | None = None
        self._replay_session: SessionRecord | None = None
        self._run_state: RunStateSnapshot | None = None
        self._busy_state = BusyStateSnapshot()
        self._runtime_info: dict[str, str] = {}
        self._theme_key = load_theme_key()

        self.setWindowTitle(BASE_WINDOW_TITLE)
        self.resize(1480, 980)
        self.setMinimumSize(1240, 840)

        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(
            TOKENS.spacing.xl,
            TOKENS.spacing.xl,
            TOKENS.spacing.xl,
            TOKENS.spacing.xl,
        )
        root_layout.setSpacing(TOKENS.spacing.lg)

        self.nav_rail = QFrame()
        self.nav_rail.setObjectName("NavRail")
        self.nav_rail.setFixedWidth(198)
        root_layout.addWidget(self.nav_rail)
        self._build_sidebar()

        self.workspace = QWidget()
        self.workspace.setObjectName("WorkspaceHost")
        root_layout.addWidget(self.workspace, stretch=1)
        self._build_content()
        self._connect_state()
        self.switch_page("new")
        self._refresh_window_chrome()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.state.shutdown()
        super().closeEvent(event)

    def _build_sidebar(self) -> None:
        layout = QVBoxLayout(self.nav_rail)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(TOKENS.spacing.sm)

        brand = QLabel("沙盘圆桌")
        brand.setObjectName("BrandTitle")
        layout.addWidget(brand)

        subtitle = QLabel("Local Workbench")
        subtitle.setObjectName("BrandSubtitle")
        layout.addWidget(subtitle)
        layout.addSpacing(TOKENS.spacing.lg)

        primary_caption = QLabel("工作区")
        primary_caption.setObjectName("RailCaption")
        layout.addWidget(primary_caption)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, NavButton] = {}

        for key in ("new", "status", "results", "replay"):
            button = NavButton(PAGE_META[key])
            button.clicked.connect(lambda checked=False, page_key=key: self.switch_page(page_key))
            self.nav_group.addButton(button)
            self.nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        status_label = QLabel("当前状态")
        status_label.setObjectName("RailCaption")
        layout.addWidget(status_label)

        self.sidebar_status = StatusPill(get_status_text("idle"), tone=get_status_tone("idle"))
        layout.addWidget(self.sidebar_status, alignment=Qt.AlignLeft)

        self.sidebar_context = QLabel("准备新建沙盘。")
        self.sidebar_context.setObjectName("SubtleText")
        self.sidebar_context.setWordWrap(True)
        layout.addWidget(self.sidebar_context)
        layout.addSpacing(TOKENS.spacing.sm)

        settings_caption = QLabel("辅助")
        settings_caption.setObjectName("RailCaption")
        layout.addWidget(settings_caption)

        settings_button = NavButton(PAGE_META["settings"])
        settings_button.clicked.connect(lambda checked=False: self.switch_page("settings"))
        self.nav_group.addButton(settings_button)
        self.nav_buttons["settings"] = settings_button
        layout.addWidget(settings_button)

        layout.addSpacing(TOKENS.spacing.sm)
        theme_caption = QLabel("主题")
        theme_caption.setObjectName("RailCaption")
        layout.addWidget(theme_caption)

        self.theme_combo = AppComboBox()
        self.theme_combo.blockSignals(True)
        for theme in available_themes():
            self.theme_combo.addItem(theme.label, theme.key)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(self._theme_key)))
        self.theme_combo.blockSignals(False)
        self.theme_combo.currentIndexChanged.connect(self._handle_sidebar_theme_changed)
        layout.addWidget(self.theme_combo)

    def _build_content(self) -> None:
        layout = QVBoxLayout(self.workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.page_stack = AnimatedStackedWidget()
        layout.addWidget(self.page_stack)

        self.new_page = NewDiscussionPage()
        self.status_page = StatusPage()
        self.results_page = ResultsPage()
        self.replay_page = ReplayPage()
        self.settings_page = SettingsPage()

        self.page_stack.addWidget(self.new_page)
        self.page_stack.addWidget(self.status_page)
        self.page_stack.addWidget(self.results_page)
        self.page_stack.addWidget(self.replay_page)
        self.page_stack.addWidget(self.settings_page)

        self.page_index = {
            "new": 0,
            "status": 1,
            "results": 2,
            "replay": 3,
            "settings": 4,
        }

        self.new_page.start_requested.connect(self._start_discussion)
        self.status_page.results_requested.connect(self._open_current_results)
        self.replay_page.session_selected.connect(self.state.load_session)
        self.replay_page.session_delete_requested.connect(self._confirm_delete_replay_session)
        self.replay_page.open_requested.connect(self._open_replay_results)
        self.replay_page.refresh_requested.connect(self._refresh_runtime_lists)
        self.settings_page.default_config_changed.connect(self.state.set_default_config_name)
        self.settings_page.api_settings_save_requested.connect(self.state.save_api_settings)
        self.settings_page.token_limit_save_requested.connect(self.state.save_config_token_limit)
        self.settings_page.api_connections_test_requested.connect(self.state.test_api_connections)
        self.settings_page.manual_models_changed.connect(self.new_page.set_manual_models)
        self.settings_page.theme_changed.connect(self._apply_theme_choice)
        self.new_page.member_add_requested.connect(self._handle_member_add_requested)
        self.new_page.member_rename_requested.connect(self._handle_member_rename_requested)
        self.new_page.skill_folder_open_requested.connect(self._open_skill_folder_for_member)
        self.new_page.skill_folder_select_requested.connect(self._select_skill_folder_for_member)
        self.settings_page.refresh_requested.connect(self._refresh_runtime_lists)
        self.new_page.set_manual_models(self.settings_page.manual_model_names())
        self._sync_theme_controls(self._theme_key)

    def _connect_state(self) -> None:
        self.state.configs_changed.connect(self._apply_configs)
        self.state.sessions_changed.connect(self._apply_sessions)
        self.state.runtime_info_changed.connect(self._apply_runtime_info)
        self.state.run_state_changed.connect(self._apply_run_state)
        self.state.results_session_changed.connect(self._apply_results_session)
        self.state.replay_session_changed.connect(self._apply_replay_session)
        self.state.default_config_changed.connect(self._apply_default_config)
        self.state.api_settings_saved.connect(self.settings_page.show_api_save_feedback)
        self.state.token_limit_saved.connect(self.settings_page.show_token_limit_save_feedback)
        self.state.api_connectivity_tested.connect(self.settings_page.show_api_connectivity_results)
        self.state.error_occurred.connect(self._show_error)
        self.state.busy_changed.connect(self._set_busy)

    def switch_page(self, page_key: str) -> None:
        self._current_page_key = page_key
        self.page_stack.setCurrentIndex(self.page_index[page_key])
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page_key)
        self._refresh_window_chrome()

    def _handle_sidebar_theme_changed(self) -> None:
        theme_key = str(self.theme_combo.currentData() or "")
        if theme_key:
            self._apply_theme_choice(theme_key)

    def _apply_theme_choice(self, theme_key: str) -> None:
        resolved_key = save_theme_key(theme_key)
        self._theme_key = resolved_key
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, resolved_key)
        self._sync_theme_controls(resolved_key)
        self.results_page.refresh_theme(resolved_key)
        self.replay_page.refresh_theme(resolved_key)

    def _sync_theme_controls(self, theme_key: str) -> None:
        for combo in (
            getattr(self, "theme_combo", None),
            getattr(getattr(self, "settings_page", None), "theme_combo", None),
        ):
            if combo is None:
                continue
            combo.blockSignals(True)
            index = combo.findData(theme_key)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _start_discussion(self, form_data: dict) -> None:
        started = self.state.start_discussion(form_data)
        if started:
            self.switch_page("status")

    def _handle_member_add_requested(self, config_name: str, display_name: str, model: str) -> None:
        added = self.state.add_config_member(
            {
                "config_name": config_name,
                "display_name": display_name,
                "model": model,
            }
        )
        if added:
            self.new_page.show_member_added_feedback(member_name=display_name)

    def _handle_member_rename_requested(
        self,
        config_name: str,
        member_id: str,
        display_name: str,
    ) -> None:
        renamed = self.state.rename_config_member(
            {
                "config_name": config_name,
                "member_id": member_id,
                "display_name": display_name,
            }
        )
        if renamed:
            self.new_page.show_member_renamed_feedback(member_name=display_name)

    def _open_current_results(self) -> None:
        self.state.show_current_results()
        self.switch_page("results")

    def _open_replay_results(self) -> None:
        self.state.show_replay_results()
        self.switch_page("results")

    def _confirm_delete_replay_session(self, session_id: str) -> None:
        reply = QMessageBox.question(
            self,
            "删除历史记录",
            (
                f"确定删除这条历史记录吗？\n\n"
                f"Session ID: {session_id}\n\n"
                "删除后将无法在历史记录中继续查看该 session。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self.replay_page.show_delete_feedback("已取消删除，历史记录未改变。")
            return

        if self.state.delete_session(session_id):
            self.replay_page.show_delete_feedback(f"已删除历史 session：{session_id}")
        else:
            self.replay_page.show_delete_feedback(f"删除历史 session 失败：{session_id}")

    def _refresh_runtime_lists(self) -> None:
        self.state.refresh_configs()
        self.state.refresh_sessions()
        self.state.refresh_runtime_info()

    def _apply_configs(self, configs: object) -> None:
        self.new_page.set_configs(configs)
        self.settings_page.set_configs(configs)

    def _apply_runtime_info(self, info: object) -> None:
        self._runtime_info = dict(info) if isinstance(info, dict) else {}
        self.settings_page.set_runtime_info(self._runtime_info)

    def _apply_sessions(self, sessions: object) -> None:
        self.replay_page.set_sessions(sessions)
        self.settings_page.set_session_count(len(sessions))
        self._refresh_window_chrome()

    def _apply_results_session(self, session: object, source: str) -> None:
        self._results_session = session if isinstance(session, SessionRecord) else None
        self._results_source = source
        self.results_page.set_session(session, source)
        self._refresh_window_chrome()

    def _apply_replay_session(self, session: object) -> None:
        self._replay_session = session if isinstance(session, SessionRecord) else None
        self.replay_page.set_preview_session(session)
        self._refresh_window_chrome()

    def _apply_default_config(self, config_name: str) -> None:
        self.new_page.set_default_config_name(config_name)
        self.settings_page.set_default_config_name(config_name)

    def _open_skill_folder_for_member(self, member_id: str) -> None:
        skills_dir = str(self._runtime_info.get("skills_dir") or "").strip()
        member_name = self._member_display_name(member_id)
        folder_path = Path(skills_dir) if skills_dir else None
        if folder_path is None or not folder_path.exists():
            self.new_page.show_skill_folder_open_feedback(
                member_name=member_name,
                folder_path=skills_dir,
                success=False,
            )
            return

        success = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
        self.new_page.show_skill_folder_open_feedback(
            member_name=member_name,
            folder_path=str(folder_path),
            success=success,
        )

    def _select_skill_folder_for_member(self, member_id: str) -> None:
        skills_dir = str(self._runtime_info.get("skills_dir") or "").strip()
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "选择 skill 文件夹",
            skills_dir,
        )
        if not folder_path:
            self.new_page.show_skill_folder_select_cancelled(
                member_name=self._member_display_name(member_id)
            )
            return
        self.new_page.add_external_skill_folder(member_id, folder_path)

    def _member_display_name(self, member_id: str) -> str:
        for config in self.state.configs:
            for member in getattr(config, "members", []):
                if getattr(member, "id", "") == member_id:
                    return getattr(member, "display_name", member_id)
        return member_id

    def _apply_run_state(self, run_state: object) -> None:
        self._run_state = run_state if isinstance(run_state, RunStateSnapshot) else None
        self.status_page.set_run_state(run_state)
        self._refresh_window_chrome()

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "操作失败", message)

    def _set_busy(self, busy_state: object) -> None:
        self._busy_state = (
            busy_state
            if isinstance(busy_state, BusyStateSnapshot)
            else BusyStateSnapshot(bootstrapping=bool(busy_state))
        )
        self.new_page.set_busy(self._is_new_discussion_busy())
        self._refresh_window_chrome()

    def _refresh_window_chrome(self) -> None:
        status_key = self._resolve_chrome_status_key()
        status_text = get_status_text(status_key)
        status_tone = get_status_tone(status_key)

        self.sidebar_status.setText(status_text)
        self.sidebar_status.set_tone(status_tone)
        self.sidebar_context.setText(self._build_sidebar_context(status_key))
        self.setWindowTitle(self._build_window_title(status_text))

    def _resolve_chrome_status_key(self) -> str:
        if self._current_page_key == "results" and self._results_session is not None:
            return normalize_status(
                getattr(self._results_session.status, "value", self._results_session.status),
                default="completed",
            )

        if self._current_page_key == "replay":
            if self._replay_session is not None:
                return normalize_status(
                    getattr(self._replay_session.status, "value", self._replay_session.status),
                    default="completed",
                )
            if self._busy_state.session_load_active:
                return "loading"
            return "waiting"

        return self._resolve_run_status_key(self._run_state, busy=self._is_run_context_busy())

    @staticmethod
    def _resolve_run_status_key(run_state: RunStateSnapshot | None, *, busy: bool = False) -> str:
        if run_state is None:
            return "loading" if busy else "idle"

        if run_state.error:
            return "failed"

        if run_state.is_running:
            if not run_state.session_id:
                return "loading"
            return "running"

        final_event = MainWindow._find_last_terminal_event(run_state.events)
        if final_event is not None:
            if final_event.event_type == ProgressEventType.SESSION_FAILED:
                return "failed"
            return normalize_status(final_event.status, default="completed")

        if run_state.completed_at is not None:
            return "completed"

        if busy:
            return "loading"

        return "waiting"

    def _is_new_discussion_busy(self) -> bool:
        return self._busy_state.discussion_active or self._busy_state.shutting_down

    def _is_run_context_busy(self) -> bool:
        return (
            self._busy_state.bootstrapping
            or self._busy_state.discussion_active
            or self._busy_state.shutting_down
        )

    @staticmethod
    def _find_last_terminal_event(
        events: list[DiscussionProgressEvent],
    ) -> DiscussionProgressEvent | None:
        for event in reversed(events):
            if event.event_type in {
                ProgressEventType.SESSION_FINISHED,
                ProgressEventType.SESSION_FAILED,
            }:
                return event
        return None

    def _build_window_title(self, status_text: str) -> str:
        parts = [BASE_WINDOW_TITLE, PAGE_META[self._current_page_key]]
        context = self._build_title_context()
        if context:
            parts.append(context)
        parts.append(status_text)
        return " · ".join(parts)

    def _build_title_context(self) -> str | None:
        if self._current_page_key == "status":
            return "当前运行"
        if self._current_page_key == "results":
            if self._results_source == RESULT_SOURCE_HISTORY_REPLAY:
                return "历史回放"
            return "当前运行结果"
        if self._current_page_key == "replay":
            return "历史回放"
        return None

    def _build_sidebar_context(self, status_key: str) -> str:
        if self._current_page_key == "new":
            if status_key == "loading":
                return "工作台正在加载配置或历史记录。"
            return "准备新建沙盘。先选配置，再填写场景。"

        if self._current_page_key == "status":
            if status_key == "loading":
                return "讨论请求已提交，正在初始化当前运行。"
            if status_key == "running":
                return "当前页展示的是这一轮讨论的实时执行状态。"
            if status_key == "degraded":
                return "本轮讨论已结束，但至少一个环节发生回退或局部失败。"
            if status_key == "failed":
                return "当前运行未完成。请结合状态页和提示信息判断失败点。"
            if status_key == "completed":
                return "当前运行已完成，可以直接进入结果页查看结论。"
            return "这里会跟踪当前运行的阶段进度和成员状态。"

        if self._current_page_key == "results":
            if self._results_source == RESULT_SOURCE_HISTORY_REPLAY:
                return "当前看到的是历史回放结果，不会覆盖当前运行上下文。"
            if status_key == "degraded":
                return "当前结果来自本轮运行，但属于降级完成，使用前请先确认可靠性。"
            if status_key == "failed":
                return "当前结果未正常完成，请优先查看失败位置和缺失内容。"
            return "当前看到的是本轮运行的结果摘要和结构化内容。"

        if self._current_page_key == "replay":
            if status_key == "loading":
                return "正在读取历史 session，请稍候。"
            return "这里用于回放历史 session，并可继续在结果页查看。"

        return "这里用于查看运行环境、配置和默认设置。"
