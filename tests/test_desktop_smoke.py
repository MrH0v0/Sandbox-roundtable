from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsOpacityEffect,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
)

from sandbox.application.workbench_service import WorkbenchService
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import RoundtableEngine
from sandbox.core.service_container import AppServices
from sandbox.desktop.main_window import MainWindow
from sandbox.desktop.pages.new_discussion_page import NewDiscussionPage
from sandbox.desktop.pages.settings_page import SettingsPage
from sandbox.desktop.pages.status_page import StatusPage
from sandbox.desktop.state import (
    RESULT_SOURCE_HISTORY_REPLAY,
    DesktopState,
    MemberRunState,
    RunStateSnapshot,
)
from sandbox.desktop.pages.results_page import ResultsPage
from sandbox.desktop.pages.replay_page import ReplayPage
from sandbox.desktop.theme import (
    available_themes,
    build_markdown_document_css,
    build_stylesheet,
)
from sandbox.desktop.widgets.common import (
    ActivityBar,
    AppButton,
    AppComboBox,
    HistoryItemWidget,
    JsonTreeWidget,
)
from sandbox.schemas.config import (
    MemberConfigSummary,
    RoundtableConfigSummary,
    SkillCatalogItem,
)
from sandbox.schemas.discussion import (
    AgentTurnResult,
    DiscussionProgressEvent,
    DiscussionStage,
    ProgressEventType,
    ResultStatus,
    RoundResult,
    Scenario,
    SessionRecord,
    SessionSummary,
    SessionStatus,
)
from sandbox.schemas.usage import TokenUsage
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeAIClient:
    def __init__(self, *, response_delay: float = 0.0) -> None:
        self.response_delay = response_delay

    async def chat_completion(self, *, model: str, messages, generation) -> str:
        if self.response_delay:
            await asyncio.sleep(self.response_delay)
        return f"{model} response"

    async def aclose(self) -> None:
        return None


class SlowWorkbenchService(WorkbenchService):
    def __init__(
        self,
        *,
        list_delay: float = 0.0,
        load_delay: float = 0.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.list_delay = list_delay
        self.load_delay = load_delay

    def list_sessions(self, *, limit: int | None = None):
        if self.list_delay:
            time.sleep(self.list_delay)
        return super().list_sessions(limit=limit)

    def load_session(self, session_id: str):
        if self.load_delay:
            time.sleep(self.load_delay)
        return super().load_session(session_id)


def _write_skill(path: Path, skill_id: str) -> None:
    path.write_text(
        f"""---
id: {skill_id}
name: "{skill_id}"
core_strategy: "strategy"
decision_priorities:
  - "priority"
risk_preference: "medium"
information_view: "info"
tempo_view: "tempo"
resource_view: "resource"
common_failure_modes:
  - "failure"
output_format_requirements:
  - "format"
---
""",
        encoding="utf-8",
    )


def _seed_session(root: Path, session_id: str = "seed-session") -> None:
    sessions_dir = root / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    SessionStore(sessions_dir).save(
        SessionRecord(
            session_id=session_id,
            config_id="demo",
            config_name="demo.yaml",
            scenario=Scenario(title="Seed Session", background="Background"),
            status=SessionStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            markdown_summary="# Seed",
        )
    )


def _build_fake_services(
    root: Path,
    *,
    list_delay: float = 0.0,
    load_delay: float = 0.0,
    response_delay: float = 0.0,
) -> AppServices:
    skills_dir = root / "skills"
    configs_dir = root / "configs"
    sessions_dir = root / "sessions"
    skills_dir.mkdir(exist_ok=True)
    configs_dir.mkdir(exist_ok=True)
    sessions_dir.mkdir(exist_ok=True)

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "model-b",
                        "skill": "beta.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    skill_loader.load_all()
    config_loader = RoundtableConfigLoader(configs_dir, skill_loader)
    session_store = SessionStore(sessions_dir)
    ai_client = FakeAIClient(response_delay=response_delay)
    roundtable_engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=ai_client,
        session_store=session_store,
    )
    workbench_service = SlowWorkbenchService(
        settings=None,
        config_loader=config_loader,
        session_store=session_store,
        roundtable_engine=roundtable_engine,
        ai_client=ai_client,
        list_delay=list_delay,
        load_delay=load_delay,
    )
    return AppServices(
        settings=None,
        skill_loader=skill_loader,
        config_loader=config_loader,
        session_store=session_store,
        ai_client=ai_client,
        roundtable_engine=roundtable_engine,
        workbench_service=workbench_service,
    )


def _get_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _clear_member_skill_settings() -> None:
    settings = QSettings("sandbox", "roundtable-desktop")
    settings.remove("member_skill_bindings")
    settings.remove("manual_model_names")
    settings.remove("theme_key")
    settings.sync()


def _demo_config_summary() -> RoundtableConfigSummary:
    return RoundtableConfigSummary(
        config_name="demo.yaml",
        id="demo",
        name="Demo",
        member_count=2,
        member_names=["Member A", "Member B"],
        moderator_name="Moderator",
        judge_name="Judge",
        members=[
            MemberConfigSummary(
                id="member-a",
                display_name="Member A",
                model="model-a",
                skills=["alpha.md"],
            ),
            MemberConfigSummary(
                id="member-b",
                display_name="Member B",
                model="model-b",
                skills=[],
            ),
        ],
        available_models=["model-a", "model-b"],
        skills=[
            SkillCatalogItem(
                id="alpha",
                name="Alpha",
                category="通用",
                source_file="alpha.md",
            ),
            SkillCatalogItem(
                id="beta",
                name="Beta",
                category="分析",
                source_file="beta.md",
            ),
        ],
    )


def _wait_until(app: QApplication, predicate, *, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_desktop_window_can_bootstrap(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()

    assert window.page_stack.count() == 5
    assert state.configs

    window.close()
    state.shutdown()
    app.processEvents()


def test_new_discussion_page_emits_member_model_skill_overrides() -> None:
    app = _get_app()
    _clear_member_skill_settings()
    page = NewDiscussionPage()
    page.set_configs([_demo_config_summary()])
    captured: list[dict] = []
    page.start_requested.connect(captured.append)

    model_combo = page.member_model_combos["member-a"]
    model_combo.setCurrentIndex(model_combo.findText("model-b"))
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == []

    page._add_skill_to_member("member-a", "beta.md")
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == ["beta.md"]

    page._remove_skill_from_member("member-a", "beta.md")
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == []

    page._add_skill_to_member("member-a", "beta.md")
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == ["beta.md"]

    model_combo.setCurrentIndex(model_combo.findText("model-a"))
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == ["alpha.md"]

    model_combo.setCurrentIndex(model_combo.findText("model-b"))
    app.processEvents()
    assert page.selected_skill_refs["member-a"] == ["beta.md"]

    page.title_input.setText("Runtime UI")
    page.background_input.setPlainText("Background")
    page._submit()

    assert captured
    member_a_override = next(
        override
        for override in captured[0]["member_overrides"]
        if override["member_id"] == "member-a"
    )
    assert member_a_override == {
        "member_id": "member-a",
        "model": "model-b",
        "skills": ["beta.md"],
    }


def test_new_discussion_page_persists_model_skill_binding() -> None:
    app = _get_app()
    settings = QSettings("sandbox", "roundtable-desktop")
    settings.remove("member_skill_bindings")

    first_page = NewDiscussionPage()
    first_page.set_configs([_demo_config_summary()])
    model_combo = first_page.member_model_combos["member-a"]
    model_combo.setCurrentIndex(model_combo.findText("model-b"))
    first_page._add_skill_to_member("member-a", "beta.md")
    settings.sync()

    second_page = NewDiscussionPage()
    second_page.set_configs([_demo_config_summary()])
    second_combo = second_page.member_model_combos["member-a"]
    second_combo.setCurrentIndex(second_combo.findText("model-b"))
    app.processEvents()

    assert second_page.selected_skill_refs["member-a"] == ["beta.md"]


def test_new_discussion_page_uses_member_bound_skill_dialog() -> None:
    app = _get_app()
    _clear_member_skill_settings()
    page = NewDiscussionPage()
    page.set_configs([_demo_config_summary()])

    assert not hasattr(page, "skill_picker_panel")
    add_button = next(
        button for button in page.findChildren(AppButton) if button.text() == "添加 skill"
    )
    add_button.click()
    app.processEvents()

    dialog = page._skill_picker_dialog
    assert isinstance(dialog, QDialog)
    assert dialog.isVisible()
    assert dialog.member_id == "member-a"

    dialog.search_input.setText("beta")
    category_index = dialog.category_combo.findData("分析")
    dialog.category_combo.setCurrentIndex(category_index)
    app.processEvents()

    assert dialog.visible_skill_refs == ["beta.md"]

    dialog_add_button = next(
        button for button in dialog.findChildren(AppButton) if button.text() == "添加"
    )
    dialog_add_button.click()
    app.processEvents()

    assert page.selected_skill_refs["member-a"] == ["alpha.md", "beta.md"]
    assert page.selected_skill_refs["member-b"] == []
    assert not dialog.isVisible()


def test_new_discussion_page_skill_dialog_filters_by_category_and_search() -> None:
    app = _get_app()
    _clear_member_skill_settings()
    page = NewDiscussionPage()
    page.set_configs([_demo_config_summary()])

    page._open_skill_picker("member-a")
    dialog = page._skill_picker_dialog
    dialog.search_input.setText("beta")
    category_index = dialog.category_combo.findData("分析")
    dialog.category_combo.setCurrentIndex(category_index)
    app.processEvents()

    assert dialog.visible_skill_refs == ["beta.md"]

    dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("通用"))
    app.processEvents()

    assert dialog.visible_skill_refs == []


def test_new_discussion_page_marks_folder_skill_labels() -> None:
    label = NewDiscussionPage._format_skill_label(
        "debate-kit",
        SkillCatalogItem(
            id="debate-kit",
            name="Debate Kit",
            category="辩论",
            source_file="debate-kit",
        ),
    )

    assert label == "Debate Kit · 辩论 · 文件夹"


def test_new_discussion_page_adds_selected_external_skill_folder(tmp_path: Path) -> None:
    app = _get_app()
    _clear_member_skill_settings()
    skill_dir = tmp_path / "external-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        """---
name: "External Skill"
category: "自定义"
---

Use this external skill.
""",
        encoding="utf-8",
    )

    page = NewDiscussionPage()
    page.set_configs([_demo_config_summary()])

    added = page.add_external_skill_folder("member-a", str(skill_dir))
    app.processEvents()

    assert added
    assert page.selected_skill_refs["member-a"] == ["alpha.md", str(skill_dir)]
    assert page._format_skill_label(str(skill_dir), page._resolve_skill(str(skill_dir))) == (
        "external-skill · 自定义 · 文件夹"
    )


def test_settings_page_manual_models_feed_new_discussion_model_choices(tmp_path: Path) -> None:
    app = _get_app()
    _clear_member_skill_settings()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    window.settings_page.manual_models_input.setPlainText(
        "gpt-5.4-mini\n"
        "qwen3.5-plus\n"
        "doubao-seed-2-0-lite"
    )
    window.settings_page.save_manual_models_button.click()
    app.processEvents()

    combo = window.new_page.member_model_combos["member-a"]
    assert combo.findText("gpt-5.4-mini") >= 0
    assert combo.findText("qwen3.5-plus") >= 0
    assert combo.findText("model-a") >= 0

    window.close()
    state.shutdown()
    app.processEvents()

    next_state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    next_window = MainWindow(next_state)
    next_state.bootstrap()
    app.processEvents()

    next_combo = next_window.new_page.member_model_combos["member-a"]
    assert next_combo.findText("qwen3.5-plus") >= 0

    next_window.close()
    next_state.shutdown()
    app.processEvents()


def test_new_discussion_page_open_skill_folder_button_emits_member_context() -> None:
    app = _get_app()
    page = NewDiscussionPage()
    page.set_configs([_demo_config_summary()])
    captured: list[str] = []
    page.skill_folder_open_requested.connect(captured.append)

    page.open_skill_folder_buttons["member-a"].click()
    app.processEvents()

    assert captured == ["member-a"]


def test_main_window_adds_member_from_new_discussion_page(tmp_path: Path) -> None:
    app = _get_app()
    _clear_member_skill_settings()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    window.new_page._submit_new_member("Member C", "model-b")
    app.processEvents()

    current_config = next(config for config in state.configs if config.config_name == "demo.yaml")
    added_member = next(member for member in current_config.members if member.display_name == "Member C")
    assert added_member.id.startswith("member-")
    assert window.new_page.member_model_combos[added_member.id].currentData() == "model-b"
    assert window.new_page.selected_skill_refs[added_member.id] == []
    assert current_config.member_count == 3
    assert "Member C" in current_config.member_names

    window.close()
    state.shutdown()
    app.processEvents()


def test_main_window_renames_member_without_changing_member_id(tmp_path: Path) -> None:
    app = _get_app()
    _clear_member_skill_settings()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    window.new_page.member_model_combos["member-a"].setCurrentIndex(
        window.new_page.member_model_combos["member-a"].findText("model-b")
    )
    window.new_page._add_skill_to_member("member-a", "beta.md")
    app.processEvents()

    window.new_page._submit_member_rename("member-a", "Renamed A")
    app.processEvents()

    current_config = next(config for config in state.configs if config.config_name == "demo.yaml")
    renamed_member = next(member for member in current_config.members if member.id == "member-a")
    assert renamed_member.display_name == "Renamed A"
    assert "Renamed A" in current_config.member_names
    assert "Member A" not in current_config.member_names
    member_a_override = next(
        override
        for override in window.new_page._build_member_overrides()
        if override["member_id"] == "member-a"
    )
    assert member_a_override["model"] == "model-b"
    assert member_a_override["skills"] == ["beta.md"]

    window.close()
    state.shutdown()
    app.processEvents()


def test_main_window_opens_runtime_skills_dir_from_member_card(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    opened_paths: list[str] = []

    def fake_open_url(url) -> bool:
        opened_paths.append(url.toLocalFile())
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", fake_open_url)
    state.runtime_info_changed.emit({"skills_dir": str(tmp_path / "skills")})
    app.processEvents()

    window.new_page.open_skill_folder_buttons["member-a"].click()
    app.processEvents()

    assert [Path(path) for path in opened_paths] == [tmp_path / "skills"]
    assert "Member A" in window.new_page.feedback_banner.body_label.text()

    window.close()
    state.shutdown()
    app.processEvents()


def test_main_window_reports_cancelled_skill_folder_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")
    window._select_skill_folder_for_member("member-a")
    app.processEvents()

    assert window.new_page.feedback_banner.title_label.text() == "已取消添加 skill"
    assert "Member A" in window.new_page.feedback_banner.body_label.text()

    window.close()
    state.shutdown()
    app.processEvents()


def test_session_refresh_and_load_are_off_ui_thread(tmp_path: Path) -> None:
    _seed_session(tmp_path, "seed-session")
    app = _get_app()
    state = DesktopState(
        service_factory=lambda: _build_fake_services(
            tmp_path,
            list_delay=0.4,
            load_delay=0.4,
        )
    )

    refresh_started_at = time.perf_counter()
    state.refresh_sessions()
    refresh_elapsed = time.perf_counter() - refresh_started_at

    assert refresh_elapsed < 0.2
    assert _wait_until(app, lambda: len(state.sessions) == 1)

    state.current_session = None
    state.current_session_changed.emit(None)

    load_started_at = time.perf_counter()
    started = state.load_session("seed-session")
    load_elapsed = time.perf_counter() - load_started_at

    assert started
    assert load_elapsed < 0.2
    assert _wait_until(
        app,
        lambda: state.current_session is not None
        and state.current_session.session_id == "seed-session",
    )

    state.shutdown()
    app.processEvents()


def test_desktop_state_can_finish_discussion_and_replay(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    state.bootstrap()

    started = state.start_discussion(
        {
            "config_name": "demo.yaml",
            "title": "Desktop Smoke Test",
            "background": "Background",
            "constraints": "Constraint A\nConstraint B",
            "friendly_forces": "Friendly A",
            "enemy_forces": "Enemy A",
            "objectives": "Objective A",
            "victory_conditions": "Victory A",
            "additional_notes": "Note A",
        }
    )

    assert started
    assert _wait_until(app, lambda: state.current_session is not None, timeout=10)
    assert state.current_session is not None
    assert state.current_session.markdown_summary
    assert state.current_session.scenario.title == "Desktop Smoke Test"

    state.refresh_sessions()
    assert _wait_until(app, lambda: len(state.sessions) == 1)

    session_id = state.sessions[0].session_id
    state.current_session = None
    state.current_session_changed.emit(None)

    loaded = state.load_session(session_id)
    assert loaded
    assert _wait_until(
        app,
        lambda: state.current_session is not None and state.current_session.session_id == session_id,
    )

    state.shutdown()
    app.processEvents()


def test_latest_history_selection_wins_when_loads_overlap(tmp_path: Path) -> None:
    _seed_session(tmp_path, "session-a")
    _seed_session(tmp_path, "session-b")
    app = _get_app()
    state = DesktopState(
        service_factory=lambda: _build_fake_services(
            tmp_path,
            load_delay=0.3,
        )
    )

    first_started = state.load_session("session-a")
    second_started = state.load_session("session-b")

    assert first_started
    assert second_started
    assert _wait_until(
        app,
        lambda: state.replay_session is not None and state.replay_session.session_id == "session-b",
        timeout=5,
    )

    state.shutdown()
    app.processEvents()


def test_refreshing_history_does_not_lock_new_discussion_form(tmp_path: Path) -> None:
    _seed_session(tmp_path, "seed-session")
    app = _get_app()
    state = DesktopState(
        service_factory=lambda: _build_fake_services(
            tmp_path,
            list_delay=0.3,
        )
    )
    window = MainWindow(state)
    state.bootstrap()
    assert _wait_until(app, lambda: state._session_refresh_worker is None)

    window.switch_page("new")
    app.processEvents()
    assert window.new_page.launch_button.isEnabled()

    state.refresh_sessions()
    assert _wait_until(
        app,
        lambda: state._session_refresh_worker is not None and state._session_refresh_worker.is_running,
    )

    app.processEvents()
    assert window.new_page.launch_button.isEnabled()
    assert window.new_page.launch_button.text() == "开始本轮讨论"

    state.shutdown()
    app.processEvents()


def test_combo_boxes_use_frameless_popup_window(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    combos = [window.new_page.config_combo, window.settings_page.default_config_combo]
    for combo in combos:
        assert isinstance(combo, AppComboBox)
        combo.showPopup()
        app.processEvents()
        popup_window = combo.popup_window()
        assert popup_window.objectName() == "ComboPopupWindow"
        assert popup_window.testAttribute(Qt.WA_TranslucentBackground)
        assert popup_window.windowFlags() & Qt.FramelessWindowHint
        assert popup_window.windowFlags() & Qt.NoDropShadowWindowHint
        combo.hidePopup()

    state.shutdown()
    app.processEvents()


def test_theme_presets_drive_stylesheet_and_markdown_css() -> None:
    themes = {theme.key: theme.label for theme in available_themes()}

    assert themes == {
        "default": "默认",
        "rem": "雷姆",
        "monochrome": "黑白",
    }
    assert "#5B93C8" in build_stylesheet("rem")
    assert "#242424" in build_stylesheet("monochrome")
    assert build_markdown_document_css("default") != build_markdown_document_css("rem")


def test_settings_page_emits_theme_selection() -> None:
    app = _get_app()
    page = SettingsPage()
    captured: list[str] = []
    page.theme_changed.connect(captured.append)

    page.theme_combo.setCurrentIndex(page.theme_combo.findData("rem"))
    app.processEvents()

    assert captured[-1] == "rem"

    page.set_theme_key("monochrome")
    assert page.theme_combo.currentData() == "monochrome"


def test_main_window_theme_switch_persists_and_syncs_controls(tmp_path: Path) -> None:
    app = _get_app()
    _clear_member_skill_settings()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    window.theme_combo.setCurrentIndex(window.theme_combo.findData("rem"))
    app.processEvents()

    settings = QSettings("sandbox", "roundtable-desktop")
    assert settings.value("theme_key", "", str) == "rem"
    assert window.settings_page.theme_combo.currentData() == "rem"
    assert "#5B93C8" in app.styleSheet()
    assert "#1B2838" in window.results_page.markdown_view.document().defaultStyleSheet()

    window._apply_theme_choice("default")
    window.close()
    state.shutdown()
    app.processEvents()


def test_app_button_flash_success_restores_base_text() -> None:
    app = _get_app()
    button = AppButton("复制 Markdown 摘要")

    button.flash_success("已复制", duration_ms=30)
    app.processEvents()

    assert button.text() == "已复制"
    assert button.property("feedback") == "success"
    assert isinstance(button.graphicsEffect(), QGraphicsOpacityEffect)
    assert _wait_until(app, lambda: button.text() == "复制 Markdown 摘要")
    assert button.property("feedback") == ""
    assert _wait_until(app, lambda: button.graphicsEffect() is None)


def test_activity_bar_pulses_only_while_visible() -> None:
    app = _get_app()
    bar = ActivityBar()

    assert bar.property("pulse") == ""

    bar.show()
    app.processEvents()

    assert bar.property("pulse") == "strong"
    assert _wait_until(app, lambda: bar.property("pulse") == "soft", timeout=1.0)

    bar.hide()
    app.processEvents()

    assert bar.property("pulse") == ""


def test_results_copy_buttons_expose_success_feedback() -> None:
    app = _get_app()
    page = ResultsPage()
    session = SessionRecord(
        session_id="copy-feedback",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Copy Feedback", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Copy Feedback",
    )
    page.set_session(session)

    page.copy_markdown_button.click()
    app.processEvents()

    assert page.copy_markdown_button.text() == "已复制 Markdown"
    assert QGuiApplication.clipboard().text() == "# Copy Feedback"

    page.copy_json_button.click()
    app.processEvents()

    assert page.copy_json_button.text() == "已复制 JSON"


def test_replay_selecting_new_session_clears_stale_preview_while_loading() -> None:
    app = _get_app()
    page = ReplayPage()
    first_session = SessionRecord(
        session_id="session-a",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Session A", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Session A",
    )
    page.set_sessions(
        [
            SessionSummary(
                session_id="session-a",
                title="Session A",
                config_name="demo.yaml",
                status="completed",
                source_path="session-a.json",
            ),
            SessionSummary(
                session_id="session-b",
                title="Session B",
                config_name="demo.yaml",
                status="completed",
                source_path="session-b.json",
            ),
        ]
    )
    page.set_preview_session(first_session)
    app.processEvents()

    page._select_session("session-b")
    app.processEvents()

    assert page.preview_stack.currentWidget() is page.preview_content
    assert page.preview_markdown.toPlainText() == "正在读取选中的历史 session..."
    assert not page.open_button.isEnabled()
    assert not page.copy_id_button.isEnabled()
    assert not page.copy_summary_button.isEnabled()


def test_replay_history_delete_button_emits_bound_session() -> None:
    app = _get_app()
    page = ReplayPage()
    page.set_sessions(
        [
            SessionSummary(
                session_id="session-a",
                title="Session A",
                config_name="demo.yaml",
                status="completed",
                source_path="session-a.json",
            ),
            SessionSummary(
                session_id="session-b",
                title="Session B",
                config_name="demo.yaml",
                status="completed",
                source_path="session-b.json",
            ),
        ]
    )
    captured: list[str] = []
    page.session_delete_requested.connect(captured.append)

    page._history_widgets["session-b"].delete_button.click()
    app.processEvents()

    assert captured == ["session-b"]


def test_main_window_confirms_and_deletes_selected_history_session(monkeypatch, tmp_path: Path) -> None:
    _seed_session(tmp_path, "session-a")
    _seed_session(tmp_path, "session-b")
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    assert _wait_until(app, lambda: len(state.sessions) == 2)
    window.switch_page("replay")
    window.replay_page._select_session("session-a")
    assert _wait_until(
        app,
        lambda: state.replay_session is not None and state.replay_session.session_id == "session-a",
    )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.replay_page._history_widgets["session-a"].delete_button.click()
    app.processEvents()

    assert not (tmp_path / "sessions" / "session-a.json").exists()
    assert (tmp_path / "sessions" / "session-b.json").exists()
    assert [summary.session_id for summary in state.sessions] == ["session-b"]
    assert "session-a" not in window.replay_page._history_widgets
    assert "已删除" in window.replay_page.list_feedback_label.text()
    assert _wait_until(
        app,
        lambda: state.replay_session is not None and state.replay_session.session_id == "session-b",
    )

    window.close()
    state.shutdown()
    app.processEvents()


def test_main_window_cancel_delete_history_session_keeps_record(monkeypatch, tmp_path: Path) -> None:
    _seed_session(tmp_path, "session-a")
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    assert _wait_until(app, lambda: len(state.sessions) == 1)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    window.replay_page._history_widgets["session-a"].delete_button.click()
    app.processEvents()

    assert (tmp_path / "sessions" / "session-a.json").exists()
    assert [summary.session_id for summary in state.sessions] == ["session-a"]
    assert "已取消删除" in window.replay_page.list_feedback_label.text()

    window.close()
    state.shutdown()
    app.processEvents()


def test_settings_page_supports_masked_api_edit_and_save_feedback(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    services = state._services
    saved_payloads: list[dict[str, str]] = []

    def fake_runtime_info() -> dict[str, str]:
        return {
            "project_root": str(tmp_path),
            "skills_dir": str(tmp_path / "skills"),
            "configs_dir": str(tmp_path / "configs"),
            "sessions_dir": str(tmp_path / "sessions"),
            "ai_provider_label": "AIHubMix",
            "aihubmix_base_url": "https://api.aihubmix.com/v1",
            "aihubmix_api_key": "seed-secret-key",
            "aihubmix_api_key_masked": "seed*******-key",
            "api_requires_restart": "true",
        }

    def fake_save_api_settings(*, provider_label: str, base_url: str, api_key: str) -> dict[str, str]:
        saved_payloads.append(
            {
                "provider_label": provider_label,
                "base_url": base_url,
                "api_key": api_key,
            }
        )
        return {
            **fake_runtime_info(),
            "ai_provider_label": provider_label,
            "aihubmix_base_url": base_url,
            "aihubmix_api_key": api_key,
            "aihubmix_api_key_masked": "new-******-7890",
        }

    services.workbench_service.get_runtime_info = fake_runtime_info
    services.workbench_service.save_api_settings = fake_save_api_settings

    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    page = window.settings_page
    assert page.api_key_input.echoMode() == QLineEdit.Password
    assert page.provider_combo.currentData() == "AIHubMix"
    assert page.base_url_input.text() == "https://api.aihubmix.com/v1"
    assert page.api_key_input.text() == "seed-secret-key"
    assert "建议重启" in page.restart_hint.body_label.text()

    page.toggle_key_button.click()
    app.processEvents()
    assert page.api_key_input.echoMode() == QLineEdit.Normal

    custom_index = page.provider_combo.findData("自定义 OpenAI 兼容接口")
    page.provider_combo.setCurrentIndex(custom_index)
    page.base_url_input.setText("https://example.com/v1")
    page.api_key_input.setText("new-secret-7890")
    page.save_api_button.click()
    app.processEvents()

    assert saved_payloads == [
        {
            "provider_label": "自定义 OpenAI 兼容接口",
            "base_url": "https://example.com/v1",
            "api_key": "new-secret-7890",
        }
    ]
    assert page.api_feedback_banner.title_label.text() == "保存成功"
    assert "建议重启桌面端" in page.api_feedback_banner.body_label.text()

    state.shutdown()
    app.processEvents()


def test_settings_page_saves_token_limit_to_current_config(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    window = MainWindow(state)
    state.bootstrap()
    window.switch_page("settings")
    app.processEvents()

    page = window.settings_page
    assert page.token_limit_spin.value() == 1200
    assert page.token_limit_save_button.isEnabled()

    page.token_limit_spin.setValue(4096)
    page.token_limit_save_button.click()
    app.processEvents()

    config_payload = yaml.safe_load((tmp_path / "configs" / "demo.yaml").read_text(encoding="utf-8"))
    role_payloads = [
        *config_payload["members"],
        config_payload["moderator"],
        config_payload["judge"],
    ]
    assert [role["generation"]["max_tokens"] for role in role_payloads] == [4096] * 4
    assert page.token_limit_feedback_banner.title_label.text() == "保存成功"
    assert "新启动的讨论" in page.token_limit_feedback_banner.body_label.text()
    assert page.token_limit_spin.value() == 4096

    window.close()
    state.shutdown()
    app.processEvents()


def test_settings_page_can_run_multiple_api_connectivity_checks(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    services = state._services

    services.workbench_service.get_runtime_info = lambda: {
        "project_root": str(tmp_path),
        "skills_dir": str(tmp_path / "skills"),
        "configs_dir": str(tmp_path / "configs"),
        "sessions_dir": str(tmp_path / "sessions"),
        "ai_provider_label": "AIHubMix",
        "aihubmix_base_url": "https://api.aihubmix.com/v1",
        "aihubmix_api_key": "seed-secret-key",
        "aihubmix_api_key_masked": "seed*******-key",
        "api_requires_restart": "true",
    }
    services.workbench_service.test_api_connections = lambda connections: [
        {"name": "主接口", "status": "success", "message": "接口可访问。"},
        {"name": "备用接口", "status": "failed", "message": "HTTP 401"},
    ]

    window = MainWindow(state)
    state.bootstrap()
    app.processEvents()

    page = window.settings_page
    page.api_test_input.setPlainText(
        "主接口 | https://api.aihubmix.com/v1 | key-a\n"
        "备用接口 | https://example.com/v1 | key-b"
    )
    page.test_connections_button.click()
    assert _wait_until(app, lambda: page.api_test_banner.title_label.text() == "多组联通测试结果")

    assert "主接口：通过" in page.api_test_banner.body_label.text()
    assert "备用接口：失败" in page.api_test_banner.body_label.text()

    state.shutdown()
    app.processEvents()


def test_settings_page_sections_do_not_overlap(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    services = state._services

    services.workbench_service.get_runtime_info = lambda: {
        "project_root": str(tmp_path),
        "skills_dir": str(tmp_path / "skills"),
        "configs_dir": str(tmp_path / "configs"),
        "sessions_dir": str(tmp_path / "sessions"),
        "ai_provider_label": "AIHubMix",
        "aihubmix_base_url": "https://api.aihubmix.com/v1",
        "aihubmix_api_key": "seed-secret-key",
        "aihubmix_api_key_masked": "seed*******-key",
        "api_requires_restart": "true",
    }

    window = MainWindow(state)
    window.resize(1280, 980)
    window.show()
    state.bootstrap()
    window.switch_page("settings")
    app.processEvents()

    page = window.settings_page

    assert page.provider_combo.geometry().bottom() < page.base_url_input.geometry().top()
    assert page.base_url_input.geometry().bottom() < page.api_key_input.geometry().top()
    assert page.api_key_input.geometry().bottom() < page.api_status_banner.geometry().top()
    assert page.project_root.geometry().bottom() < page.skills_dir.geometry().top()
    assert page.skills_dir.geometry().bottom() < page.configs_dir.geometry().top()
    assert page.configs_dir.geometry().bottom() < page.sessions_dir.geometry().top()
    assert page.sessions_dir.geometry().bottom() < page.api_base_url_block.geometry().top()

    window.close()
    state.shutdown()
    app.processEvents()


def test_status_page_reuses_member_cards_and_event_items_between_updates() -> None:
    app = _get_app()
    page = StatusPage()
    timestamp = datetime.now(timezone.utc)

    initial_event = DiscussionProgressEvent(
        event_type=ProgressEventType.MEMBER_STARTED,
        session_id="session-1",
        created_at=timestamp,
        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
        member_id="member-a",
        member_name="Member A",
        message="Member A started.",
    )
    initial_state = RunStateSnapshot(
        session_id="session-1",
        scenario_title="Reuse Test",
        config_name="demo.yaml",
        is_running=True,
        started_at=timestamp,
        current_stage=DiscussionStage.INDEPENDENT_JUDGMENT,
        member_states={
            "member-a": MemberRunState(
                member_id="member-a",
                name="Member A",
                model="model-a",
                status="waiting",
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                updated_at=timestamp,
            )
        },
        events=[initial_event],
    )
    page.set_run_state(initial_state)
    app.processEvents()

    initial_member_card = page.member_grid.itemAtPosition(0, 0).widget()
    initial_event_item = page.events_list.item(0)

    updated_event = DiscussionProgressEvent(
        event_type=ProgressEventType.MEMBER_FINISHED,
        session_id="session-1",
        created_at=datetime.now(timezone.utc),
        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
        member_id="member-a",
        member_name="Member A",
        status="success",
        message="Member A finished.",
    )
    updated_state = RunStateSnapshot(
        session_id="session-1",
        scenario_title="Reuse Test",
        config_name="demo.yaml",
        is_running=True,
        started_at=timestamp,
        current_stage=DiscussionStage.CROSS_QUESTION,
        member_states={
            "member-a": MemberRunState(
                member_id="member-a",
                name="Member A",
                model="model-a",
                status="running",
                stage=DiscussionStage.CROSS_QUESTION,
                updated_at=updated_event.created_at,
            )
        },
        events=[initial_event, updated_event],
    )
    page.set_run_state(updated_state)
    app.processEvents()

    assert page.member_grid.itemAtPosition(0, 0).widget() is initial_member_card
    assert page.events_list.item(1) is initial_event_item


def test_desktop_state_accumulates_token_usage_from_progress_events(tmp_path: Path) -> None:
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path))
    state.run_state = RunStateSnapshot(is_running=True)

    state._handle_progress(
        DiscussionProgressEvent(
            event_type=ProgressEventType.MEMBER_FINISHED,
            session_id="session-1",
            created_at=datetime.now(timezone.utc),
            stage=DiscussionStage.INDEPENDENT_JUDGMENT,
            member_id="member-a",
            member_name="Member A",
            status="success",
            data={
                "token_usage": {
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "total_tokens": 140,
                    "call_count": 1,
                }
            },
        )
    )

    assert state.run_state.token_usage.input_tokens == 100
    assert state.run_state.token_usage.output_tokens == 40
    assert state.run_state.token_usage.total_tokens == 140
    assert state.run_state.token_usage.call_count == 1

    state.shutdown()


def test_status_page_displays_token_usage_summary() -> None:
    app = _get_app()
    page = StatusPage()
    page.set_run_state(
        RunStateSnapshot(
            session_id="session-usage",
            scenario_title="Usage",
            config_name="demo.yaml",
            is_running=True,
            token_usage=TokenUsage(
                input_tokens=1200,
                output_tokens=345,
                total_tokens=1545,
                call_count=3,
            ),
        )
    )
    app.processEvents()

    assert page.token_total_block.value_label.text() == "1,545"
    assert page.token_io_block.value_label.text() == "输入 1,200 / 输出 345"
    assert page.token_call_block.value_label.text() == "3 次调用"


def test_status_page_preserves_summary_and_event_widths() -> None:
    _get_app()
    page = StatusPage()

    assert page.status_summary_panel.minimumWidth() >= 280
    assert page.member_card.minimumHeight() >= 360
    assert page.event_card.minimumWidth() >= 320
    assert page.event_card.minimumHeight() >= 360
    assert page.events_list.wordWrap()


def test_results_page_displays_session_token_usage_summary() -> None:
    app = _get_app()
    page = ResultsPage()
    session = SessionRecord(
        session_id="result-usage",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Usage Result", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Usage Result",
        token_usage=TokenUsage(
            input_tokens=1500,
            output_tokens=722,
            total_tokens=2222,
            call_count=4,
        ),
    )
    page.set_session(session)
    app.processEvents()

    assert page.token_total_block.value_label.text() == "2,222"
    assert page.token_io_block.value_label.text() == "输入 1,500 / 输出 722"
    assert page.token_call_block.value_label.text() == "4 次调用"


def test_results_and_replay_pages_copy_normalized_session_markdown() -> None:
    app = _get_app()
    timestamp = datetime.now(timezone.utc)
    session = SessionRecord(
        session_id="normalized-display",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Normalized Display", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=timestamp,
        completed_at=timestamp,
        markdown_summary="# stale summary\ncompressed",
        rounds=[
            RoundResult(
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                status=ResultStatus.SUCCESS,
                member_results=[
                    AgentTurnResult(
                        agent_id="member-a",
                        agent_name="Member A",
                        model="model-a",
                        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                        content="## 判断\n正文。",
                        started_at=timestamp,
                        finished_at=timestamp,
                        latency_ms=1,
                    )
                ],
                started_at=timestamp,
                finished_at=timestamp,
            )
        ],
    )

    results_page = ResultsPage()
    results_page.set_session(session)
    results_page.copy_markdown_button.click()
    app.processEvents()
    copied_result = QGuiApplication.clipboard().text()
    assert "# stale summary" not in copied_result
    assert "# Normalized Display" in copied_result
    assert "## 讨论过程" in copied_result

    replay_page = ReplayPage()
    replay_page.set_preview_session(session)
    replay_page.copy_summary_button.click()
    app.processEvents()
    copied_replay = QGuiApplication.clipboard().text()
    assert "# stale summary" not in copied_replay
    assert "# Normalized Display" in copied_replay
    assert "## 讨论过程" in copied_replay


def test_results_page_exports_current_session_markdown_and_text(monkeypatch, tmp_path: Path) -> None:
    app = _get_app()
    timestamp = datetime.now(timezone.utc)
    session = SessionRecord(
        session_id="result-export-session",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Result Export", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=timestamp,
        completed_at=timestamp,
        markdown_summary="# stale summary\ncompressed",
        rounds=[
            RoundResult(
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                status=ResultStatus.SUCCESS,
                member_results=[
                    AgentTurnResult(
                        agent_id="member-a",
                        agent_name="Member A",
                        model="model-a",
                        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                        content="## 判断\n正文。\n- 要点 A",
                        started_at=timestamp,
                        finished_at=timestamp,
                        latency_ms=1,
                    )
                ],
                started_at=timestamp,
                finished_at=timestamp,
            )
        ],
    )
    page = ResultsPage()
    page.set_session(session)
    md_path = tmp_path / "result.md"
    txt_path = tmp_path / "result.txt"
    selected_paths = [str(md_path), str(txt_path)]

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (selected_paths.pop(0), ""),
    )

    page.export_markdown_button.click()
    app.processEvents()
    page.export_text_button.click()
    app.processEvents()

    markdown = md_path.read_text(encoding="utf-8")
    text = txt_path.read_text(encoding="utf-8")
    assert "# stale summary" not in markdown
    assert "# Result Export" in markdown
    assert "## 讨论过程" in markdown
    assert "- 要点 A" in markdown
    assert "# " not in text
    assert "Result Export" in text
    assert "讨论过程" in text
    assert "要点 A" in text
    assert "已导出 TXT" in page.reading_hint.text()
    assert str(txt_path) not in page.reading_hint.text()
    assert txt_path.name in page.reading_hint.text()


def test_replay_page_exports_selected_session_and_handles_cancel(
    monkeypatch,
    tmp_path: Path,
) -> None:
    app = _get_app()
    selected = SessionRecord(
        session_id="selected-replay-session",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Selected Replay", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Selected Replay\n\n正文。",
    )
    page = ReplayPage()
    page.set_preview_session(selected)
    export_path = tmp_path / "selected.txt"
    selected_paths = [str(export_path), ""]

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (selected_paths.pop(0), ""),
    )

    page.export_text_button.click()
    app.processEvents()
    assert "已导出 TXT" in page.export_feedback_label.text()
    assert str(export_path) not in page.export_feedback_label.text()
    assert export_path.name in page.export_feedback_label.text()
    page.export_markdown_button.click()
    app.processEvents()

    exported_text = export_path.read_text(encoding="utf-8")
    assert "Selected Replay" in exported_text
    assert "正文。" in exported_text
    assert "# " not in exported_text
    assert "已取消导出" in page.export_feedback_label.text()


def test_results_page_preserves_summary_width() -> None:
    _get_app()
    page = ResultsPage()

    assert page.result_summary_panel.minimumWidth() >= 280
    assert page.reading_card.minimumHeight() >= 420
    assert page.markdown_view.minimumHeight() >= 360
    assert page.json_view.minimumHeight() >= 360


def test_results_page_top_summary_stays_compact_with_long_session_id() -> None:
    app = _get_app()
    page = ResultsPage()
    page.resize(1400, 760)
    page.show()
    long_session_id = "907c23c24a47acae08bfd9891525d6-extra-long-session-id"
    session = SessionRecord(
        session_id=long_session_id,
        config_id="demo",
        config_name="roundtable.example.with.very.long.profile.name.yaml",
        scenario=Scenario(
            title="Long scenario title that should not stretch the top result summary area",
            background="Background",
        ),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Result",
    )

    page.set_session(session)
    app.processEvents()

    metrics_top = page.result_metrics_panel.mapTo(page, page.result_metrics_panel.rect().topLeft()).y()
    source_top = page.result_summary_panel.mapTo(page, page.result_summary_panel.rect().topLeft()).y()
    assert abs(metrics_top - source_top) <= 4
    assert 48 <= page.result_metrics_panel.height() <= 120
    assert page.result_summary_panel.sizePolicy().verticalPolicy() == QSizePolicy.Maximum
    assert page.session_value_label.text() != long_session_id
    assert "..." in page.session_value_label.text()
    assert page.session_value_label.toolTip() == long_session_id
    assert page.round_value_label.maximumWidth() <= 96
    page.close()


def test_replay_page_preserves_summary_reading_height() -> None:
    _get_app()
    page = ReplayPage()

    assert page.reading_card.minimumHeight() >= 420
    assert page.preview_markdown.minimumHeight() >= 340


def test_results_page_uses_reader_scroll_for_long_markdown() -> None:
    app = _get_app()
    page = ResultsPage()
    page.resize(900, 520)
    page.show()
    session = SessionRecord(
        session_id="result-scroll",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Long Result", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Long Result\n\n" + "\n\n".join(
            f"Section {index}: " + "detail " * 24
            for index in range(80)
        ),
    )

    page.set_session(session)
    app.processEvents()

    assert page.content_scroll.verticalScrollBar().maximum() > 0
    assert page.markdown_view.verticalScrollBar().maximum() > 0
    assert page.markdown_view.height() <= 640
    assert page.view_stack.height() <= 680
    assert page.content_scroll.verticalScrollBar().maximum() < page.markdown_view.document().size().height()
    assert page.reading_card.geometry().bottom() <= page.content.height()
    page.close()


def test_results_context_badges_expand_for_long_dynamic_values() -> None:
    app = _get_app()
    page = ResultsPage()
    page.resize(1000, 640)
    page.show()
    session = SessionRecord(
        session_id="907c23c24a47acae08bfd9891525d6-extra-long-session-id",
        config_id="demo",
        config_name="roundtable.example.with.very.long.profile.name.yaml",
        scenario=Scenario(
            title="中国武统台湾超长标题用于验证信息卡片是否能稳定换行",
            background="Background",
        ),
        status=SessionStatus.DEGRADED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Result",
    )

    page.set_session(session)
    app.processEvents()

    badges = [
        page.context_source,
        page.context_status,
        page.context_config,
        page.context_session,
        page.context_rounds,
        page.context_title,
    ]
    for badge in badges:
        assert badge.value_label.wordWrap()
        assert badge.height() >= badge.sizeHint().height()
        assert badge.value_label.geometry().bottom() <= badge.contentsRect().bottom()
    assert "\u200b" in page.context_session.value_label.text()
    assert "\u200b" in page.context_config.value_label.text()

    page.close()


def test_replay_page_uses_inner_markdown_scroll_for_long_preview() -> None:
    app = _get_app()
    page = ReplayPage()
    page.resize(1100, 560)
    page.show()
    session = SessionRecord(
        session_id="replay-scroll",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Long Replay", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# Long Replay\n\n" + "\n\n".join(
            f"Decision {index}: " + "evidence " * 22
            for index in range(70)
        ),
    )

    page.set_preview_session(session)
    app.processEvents()

    assert page.preview_markdown.verticalScrollBar().maximum() > 0
    assert page.preview_markdown.sizePolicy().verticalPolicy() == QSizePolicy.Expanding
    assert page.preview_markdown.height() < page.preview_markdown.document().size().height()
    assert page.page_scroll.verticalScrollBar().maximum() < page.preview_markdown.document().size().height()
    assert page.reading_card.geometry().bottom() <= page.scroll_content.height()
    page.close()


def test_history_item_splits_long_metadata_into_readable_lines() -> None:
    app = _get_app()
    item = HistoryItemWidget(
        title="中国武统台湾超长历史标题",
        meta=(
            "roundtable.example.with.long.filename.yaml · "
            "降级完成 · 4 个阶段 · 2026-04-18 05:58"
        ),
        status="degraded",
    )
    item.resize(420, 120)
    item.show()
    app.processEvents()

    assert "\n" in item.meta_label.text()
    assert item.meta_label.wordWrap()
    assert item.meta_label.geometry().top() > item.title_label.geometry().bottom()
    assert item.meta_label.geometry().bottom() <= item.contentsRect().bottom()

    item.close()


def test_status_summary_panel_carries_long_token_values() -> None:
    app = _get_app()
    page = StatusPage()
    page.resize(1160, 640)
    page.show()
    page.set_run_state(
        RunStateSnapshot(
            session_id="907c23c24a47acae08bfd9891525d6",
            scenario_title="中国武统台湾",
            config_name="roundtable.example.with.long.filename.yaml",
            is_running=False,
            token_usage=TokenUsage(
                input_tokens=38474,
                output_tokens=6361,
                total_tokens=44835,
                call_count=128,
            ),
        )
    )
    app.processEvents()

    assert page.status_summary_panel.minimumWidth() >= 340
    for block in (page.token_total_block, page.token_io_block, page.token_call_block):
        assert block.value_label.wordWrap()
        assert block.value_label.height() >= block.value_label.sizeHint().height()

    page.close()


def test_status_summary_labels_have_vertical_text_room() -> None:
    app = _get_app()
    page = StatusPage()
    page.set_run_state(
        RunStateSnapshot(
            session_id="907c23c24a47acae08bfd9891525d6",
            scenario_title="中国大陆武统台湾",
            config_name="roundtable.example.yaml",
            is_running=True,
            token_usage=TokenUsage(
                input_tokens=38474,
                output_tokens=6361,
                total_tokens=44835,
                call_count=128,
            ),
        )
    )
    page.show()
    app.processEvents()

    labels = [
        page.token_total_block.title_label,
        page.token_total_block.value_label,
        page.token_io_block.title_label,
        page.token_io_block.value_label,
        page.token_call_block.title_label,
        page.token_call_block.value_label,
    ]
    for label in labels:
        assert label.minimumHeight() >= label.fontMetrics().height() + 4
        assert label.height() >= label.fontMetrics().height() + 4

    page.close()


def test_json_tree_summarizes_nested_objects_and_arrays() -> None:
    app = _get_app()
    tree = JsonTreeWidget()
    tree.set_json_data(
        {
            "scenario": {"title": "Nested"},
            "rounds": [{"stage": "one"}],
            "empty": [],
        }
    )
    app.processEvents()

    root = tree.topLevelItem(0)
    assert root.text(0) == "session"
    assert root.text(1) == "object · 3 fields"

    scenario = root.child(0)
    rounds = root.child(1)
    empty = root.child(2)
    assert scenario.text(1) == "object · 1 field"
    assert rounds.text(1) == "array · 1 item"
    assert empty.text(1) == "array · empty"


def test_shutdown_exposes_feedback_while_waiting_for_background_work(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(
        service_factory=lambda: _build_fake_services(
            tmp_path,
            response_delay=0.15,
        )
    )
    state.bootstrap()

    started = state.start_discussion(
        {
            "config_name": "demo.yaml",
            "title": "Shutdown Test",
            "background": "Background",
            "constraints": "Constraint",
            "friendly_forces": "Friendly",
            "enemy_forces": "Enemy",
            "objectives": "Objective",
            "victory_conditions": "Victory",
            "additional_notes": "Note",
        }
    )
    assert started
    assert _wait_until(app, lambda: state.run_state is not None and state.run_state.is_running)

    shutdown_started_at = time.perf_counter()
    state.shutdown()
    shutdown_elapsed = time.perf_counter() - shutdown_started_at

    assert shutdown_elapsed < 5.0
    assert state.run_state is not None
    assert "Closing" in state.run_state.last_message or "Shutdown" in state.run_state.last_message
    app.processEvents()


def test_main_window_status_and_title_follow_context(tmp_path: Path) -> None:
    app = _get_app()
    state = DesktopState(service_factory=lambda: _build_fake_services(tmp_path, response_delay=0.15))
    window = MainWindow(state)
    state.bootstrap()

    assert window.sidebar_status.text() in {"未开始", "加载中"}
    assert "新建沙盘" in window.windowTitle()

    started = state.start_discussion(
        {
            "config_name": "demo.yaml",
            "title": "Status Chrome Test",
            "background": "Background",
            "constraints": "Constraint",
            "friendly_forces": "Friendly",
            "enemy_forces": "Enemy",
            "objectives": "Objective",
            "victory_conditions": "Victory",
            "additional_notes": "Note",
        }
    )
    assert started
    window.switch_page("status")
    app.processEvents()
    assert window.sidebar_status.text() == "加载中"
    assert "运行状态" in window.windowTitle()

    assert _wait_until(
        app,
        lambda: state.run_state is not None and bool(state.run_state.session_id) and state.run_state.is_running,
    )
    assert window.sidebar_status.text() == "运行中"

    assert _wait_until(app, lambda: state.current_session is not None, timeout=10)
    app.processEvents()
    assert window.sidebar_status.text() == "已完成"

    state.show_current_results()
    window.switch_page("results")
    app.processEvents()
    assert "当前运行结果" in window.windowTitle()

    history_session = SessionRecord(
        session_id="history-session",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="History Session", background="Background"),
        status=SessionStatus.DEGRADED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# History",
    )
    window._apply_results_session(history_session, RESULT_SOURCE_HISTORY_REPLAY)
    window.switch_page("results")
    app.processEvents()
    assert window.sidebar_status.text() == "降级完成"
    assert "历史回放" in window.windowTitle()

    degraded_run = RunStateSnapshot(
        session_id="degraded-run",
        scenario_title="Degraded Run",
        config_name="demo.yaml",
        is_running=False,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        last_message="Discussion finished with status degraded.",
        events=[
            DiscussionProgressEvent(
                event_type=ProgressEventType.SESSION_FINISHED,
                session_id="degraded-run",
                created_at=datetime.now(timezone.utc),
                status="degraded",
                message="Discussion finished with status degraded.",
            )
        ],
    )
    window._apply_run_state(degraded_run)
    window.switch_page("status")
    app.processEvents()
    assert window.sidebar_status.text() == "降级完成"

    failed_run = RunStateSnapshot(
        session_id="failed-run",
        scenario_title="Failed Run",
        config_name="demo.yaml",
        is_running=False,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        last_message="Discussion failed.",
        error="forced fatal error",
        events=[
            DiscussionProgressEvent(
                event_type=ProgressEventType.SESSION_FAILED,
                session_id="failed-run",
                created_at=datetime.now(timezone.utc),
                status="failed",
                error="forced fatal error",
                message="Discussion failed before completion.",
            )
        ],
    )
    window._apply_run_state(failed_run)
    app.processEvents()
    assert window.sidebar_status.text() == "失败"
    assert "失败" in window.windowTitle()

    window.close()
    state.shutdown()
    app.processEvents()
