from __future__ import annotations

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.theme import available_themes
from sandbox.desktop.widgets.common import (
    AppButton,
    AppComboBox,
    CardFrame,
    MessageBanner,
    SectionHeader,
    ValueBlock,
)
from sandbox.schemas.config import RoundtableConfigSummary


AI_PROVIDER_PRESETS = {
    "AIHubMix": "https://api.aihubmix.com/v1",
    "自定义 OpenAI 兼容接口": "",
}


class SettingsPage(QWidget):
    default_config_changed = Signal(str)
    refresh_requested = Signal()
    api_settings_save_requested = Signal(dict)
    token_limit_save_requested = Signal(dict)
    api_connections_test_requested = Signal(dict)
    manual_models_changed = Signal(object)
    theme_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self._runtime_info: dict[str, str] = {}
        self._config_token_limits: dict[str, tuple[int, bool]] = {}
        self._api_key_visible = False
        self._theme_options = available_themes()
        self._settings = QSettings("sandbox", "roundtable-desktop")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area)

        canvas = QWidget()
        canvas.setObjectName("PageCanvas")
        self.canvas_layout = QVBoxLayout(canvas)
        self.canvas_layout.setContentsMargins(0, 0, 0, TOKENS.spacing.xxl)
        self.canvas_layout.setSpacing(TOKENS.spacing.lg)
        scroll_area.setWidget(canvas)

        self._build_intro()
        self._build_body()

    def manual_model_names(self) -> list[str]:
        return self._parse_manual_models(self.manual_models_input.toPlainText())

    def set_runtime_info(self, info: dict[str, str]) -> None:
        self._runtime_info = dict(info)
        self.project_root.set_value(info.get("project_root", "—"))
        self.skills_dir.set_value(info.get("skills_dir", "—"))
        self.configs_dir.set_value(info.get("configs_dir", "—"))
        self.sessions_dir.set_value(info.get("sessions_dir", "—"))
        self.api_base_url_block.set_value(info.get("aihubmix_base_url", "—"))

        provider_label = info.get("ai_provider_label", "AIHubMix")
        provider_index = self.provider_combo.findData(provider_label)
        if provider_index < 0:
            provider_index = self.provider_combo.findData("自定义 OpenAI 兼容接口")

        self.provider_combo.blockSignals(True)
        if provider_index >= 0:
            self.provider_combo.setCurrentIndex(provider_index)
        self.provider_combo.blockSignals(False)

        self.base_url_input.setText(info.get("aihubmix_base_url", "").strip())
        self.api_key_input.setText(info.get("aihubmix_api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Normal if self._api_key_visible else QLineEdit.Password)

        masked_value = info.get("aihubmix_api_key_masked", "未设置")
        self.api_status_banner.set_message(
            "当前连接信息",
            f"当前提供方：{provider_label}；当前 Key 状态：{masked_value}",
            tone="info",
        )
        self.restart_hint.set_message(
            "生效说明",
            "保存后会写回 `.env`，并同步当前桌面端服务对象。为避免旧缓存或已创建链路残留，建议重启桌面端后再继续新讨论。",
            tone="warning" if info.get("api_requires_restart") == "true" else "info",
        )

    def set_configs(self, configs: list[RoundtableConfigSummary]) -> None:
        current_name = self.default_config_combo.currentData()
        self._config_token_limits = {
            config.config_name: (
                config.generation_max_tokens,
                config.generation_max_tokens_mixed,
            )
            for config in configs
        }
        self.default_config_combo.blockSignals(True)
        self.default_config_combo.clear()

        for config in configs:
            self.default_config_combo.addItem(config.name, config.config_name)

        if current_name:
            index = self.default_config_combo.findData(current_name)
            if index >= 0:
                self.default_config_combo.setCurrentIndex(index)

        self.default_config_combo.blockSignals(False)
        self.config_count_block.set_value(str(len(configs)))
        self._apply_selected_token_limit()
        if configs:
            self.default_banner.set_message(
                "默认配置",
                "这里只影响“新建沙盘”页的预选项，不会反向改写已有配置文件。",
                tone="info",
            )
            return

        self.default_banner.set_message(
            "没有可用配置",
            "请先检查 `configs/` 目录和 skill 引用是否完整，再回来刷新列表。",
            tone="warning",
        )

    def set_default_config_name(self, config_name: str) -> None:
        self.default_config_combo.blockSignals(True)
        index = self.default_config_combo.findData(config_name)
        if index >= 0:
            self.default_config_combo.setCurrentIndex(index)
        self.default_config_combo.blockSignals(False)
        self._apply_selected_token_limit()

    def set_session_count(self, count: int) -> None:
        self.session_count_block.set_value(str(count))

    def show_api_save_feedback(self, success: bool, message: str) -> None:
        self.save_api_button.set_loading(False)
        self.api_feedback_banner.set_message(
            "保存成功" if success else "保存失败",
            message,
            tone="success" if success else "danger",
        )

    def show_token_limit_save_feedback(self, success: bool, message: str) -> None:
        self.token_limit_save_button.set_loading(False)
        self.token_limit_feedback_banner.set_message(
            "保存成功" if success else "保存失败",
            message,
            tone="success" if success else "danger",
        )
        if success:
            self.token_limit_save_button.flash_success("已保存")

    def show_api_connectivity_results(self, results: object) -> None:
        self.test_connections_button.set_loading(False)
        if not isinstance(results, list) or not results:
            self.api_test_banner.set_message("联通测试失败", "没有收到可显示的测试结果。", tone="danger")
            return

        lines: list[str] = []
        has_failure = False
        for item in results:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "未命名 API")
            status = str(item.get("status") or "failed")
            message = str(item.get("message") or "")
            prefix = "通过" if status == "success" else "失败"
            if status != "success":
                has_failure = True
            lines.append(f"{name}：{prefix}，{message}")

        self.api_test_banner.set_message(
            "多组联通测试结果",
            "\n".join(lines),
            tone="warning" if has_failure else "success",
        )

    def _build_intro(self) -> None:
        intro = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        intro.body.addWidget(
            SectionHeader(
                "设置",
                "本地设置",
                eyebrow="Setting",
                tone="page",
            )
        )

        self.intro_banner = MessageBanner(tone="info")
        self.intro_banner.set_message(
            "最小接入",
            "API 设置会复用现有 `.env -> load_settings() -> WorkbenchService` 链路保存，不新增并行配置系统。",
            tone="info",
        )
        intro.body.addWidget(self.intro_banner)
        self.canvas_layout.addWidget(intro)

    def _build_body(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing.lg)
        self.canvas_layout.addLayout(row)

        left_column_host = QWidget()
        left_column_host.setObjectName("PageColumn")
        left_column = QVBoxLayout(left_column_host)
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(TOKENS.spacing.lg)
        row.addWidget(left_column_host, stretch=6)

        right_column_host = QWidget()
        right_column_host.setObjectName("SideColumn")
        right_column = QVBoxLayout(right_column_host)
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(TOKENS.spacing.lg)
        row.addWidget(right_column_host, stretch=4)

        self._build_api_card(left_column)
        self._build_paths_card(left_column)
        self._build_theme_card(right_column)
        self._build_defaults_card(right_column)
        self._build_token_limit_card(right_column)
        self._build_manual_models_card(right_column)
        self._build_stats_card(right_column)
        right_column.addStretch(1)

    def set_theme_key(self, theme_key: str) -> None:
        self.theme_combo.blockSignals(True)
        index = self.theme_combo.findData(theme_key)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        self.theme_combo.blockSignals(False)

    def _build_api_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "快速调整 API",
                "在当前设置页直接查看并修改 API 提供方、接口地址与 API Key，避免来回切配置文件。",
            )
        )

        provider_label = QLabel("API 提供方")
        provider_label.setObjectName("FieldLabel")
        card.body.addWidget(provider_label)

        self.provider_combo = AppComboBox()
        for label in AI_PROVIDER_PRESETS:
            self.provider_combo.addItem(label, label)
        self.provider_combo.currentIndexChanged.connect(self._apply_provider_preset)
        card.body.addWidget(self.provider_combo)

        base_url_label = QLabel("接口地址 / Base URL")
        base_url_label.setObjectName("FieldLabel")
        card.body.addWidget(base_url_label)

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api.aihubmix.com/v1")
        card.body.addWidget(self.base_url_input)

        api_key_label = QLabel("API Key")
        api_key_label.setObjectName("FieldLabel")
        card.body.addWidget(api_key_label)

        api_key_row = QHBoxLayout()
        api_key_row.setSpacing(TOKENS.spacing.sm)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入新的 API Key")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        api_key_row.addWidget(self.api_key_input, stretch=1)

        self.toggle_key_button = AppButton("显示", tone="ghost")
        self.toggle_key_button.clicked.connect(self._toggle_api_key_visibility)
        api_key_row.addWidget(self.toggle_key_button)
        card.body.addLayout(api_key_row)

        hint = QLabel("API Key 默认掩码显示；点击“显示”后才会明文展示，保存后会写回现有 `.env`。")
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        self.api_status_banner = MessageBanner(tone="info")
        card.body.addWidget(self.api_status_banner)

        self.restart_hint = MessageBanner(tone="warning")
        card.body.addWidget(self.restart_hint)

        actions = QHBoxLayout()
        actions.setSpacing(TOKENS.spacing.sm)
        self.save_api_button = AppButton("保存 API 设置", tone="primary")
        self.save_api_button.clicked.connect(self._emit_api_save_request)
        actions.addWidget(self.save_api_button)

        refresh_button = AppButton("重新读取", tone="secondary")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        actions.addWidget(refresh_button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        self.api_feedback_banner = MessageBanner(tone="info")
        card.body.addWidget(self.api_feedback_banner)

        test_header = SectionHeader(
            "多个 API 联通测试",
            "仅做临时探测，不会改写当前正式配置。每行一组：名称 | Base URL | API Key",
        )
        card.body.addWidget(test_header)

        self.api_test_input = QPlainTextEdit()
        self.api_test_input.setPlaceholderText(
            "主接口 | https://api.aihubmix.com/v1 | API_KEY_PLACEHOLDER\n备用接口 | https://example.com/v1 | API_KEY_PLACEHOLDER"
        )
        self.api_test_input.setMinimumHeight(130)
        card.body.addWidget(self.api_test_input)

        test_actions = QHBoxLayout()
        test_actions.setSpacing(TOKENS.spacing.sm)
        self.test_connections_button = AppButton("测试多组 API", tone="secondary")
        self.test_connections_button.clicked.connect(self._emit_api_connections_test_request)
        test_actions.addWidget(self.test_connections_button)
        test_actions.addStretch(1)
        card.body.addLayout(test_actions)

        self.api_test_banner = MessageBanner(tone="info")
        card.body.addWidget(self.api_test_banner)
        parent_layout.addWidget(card)

    def _build_paths_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        card.body.addWidget(
            SectionHeader(
                "运行路径",
                "这些目录和接口地址用于确认当前桌面端到底复用了哪一套本地资源，方便排查配置缺失或落盘位置错误。",
            )
        )

        paths_layout = QVBoxLayout()
        paths_layout.setSpacing(TOKENS.spacing.md)
        self.project_root = ValueBlock("项目根目录")
        self.skills_dir = ValueBlock("Skills 目录")
        self.configs_dir = ValueBlock("Configs 目录")
        self.sessions_dir = ValueBlock("Session 目录")
        self.api_base_url_block = ValueBlock("当前接口地址")
        paths_layout.addWidget(self.project_root)
        paths_layout.addWidget(self.skills_dir)
        paths_layout.addWidget(self.configs_dir)
        paths_layout.addWidget(self.sessions_dir)
        paths_layout.addWidget(self.api_base_url_block)
        card.body.addLayout(paths_layout)

        hint = QLabel("如果需要调整这些路径，仍然应修改 `.env` 或现有配置文件后再重启桌面端。")
        hint.setObjectName("SubtleText")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        parent_layout.addWidget(card)

    def _build_theme_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "界面主题",
                "切换后会立即应用到主背景、卡片、按钮、输入框、状态标签和阅读区。",
            )
        )

        label = QLabel("当前主题")
        label.setObjectName("FieldLabel")
        card.body.addWidget(label)

        self.theme_combo = AppComboBox()
        for theme in self._theme_options:
            self.theme_combo.addItem(theme.label, theme.key)
        self.theme_combo.currentIndexChanged.connect(self._emit_theme_changed)
        card.body.addWidget(self.theme_combo)

        self.theme_banner = MessageBanner(tone="info")
        self.theme_banner.set_message(
            "即时生效",
            "主题选择会保存到本机设置，下次启动继续使用。",
            tone="info",
        )
        card.body.addWidget(self.theme_banner)
        parent_layout.addWidget(card)

    def _build_defaults_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "默认加载项",
                "高频且低风险的默认项。",
            )
        )

        combo_label = QLabel("默认配置文件")
        combo_label.setObjectName("FieldLabel")
        card.body.addWidget(combo_label)

        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing.sm)
        self.default_config_combo = AppComboBox()
        self.default_config_combo.currentIndexChanged.connect(self._emit_default_config)
        row.addWidget(self.default_config_combo, stretch=1)

        refresh_button = AppButton("刷新", tone="ghost")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        row.addWidget(refresh_button)
        card.body.addLayout(row)

        self.default_banner = MessageBanner(tone="info")
        card.body.addWidget(self.default_banner)
        parent_layout.addWidget(card)

    def _build_token_limit_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "单次生成 token 上限",
                "写入当前默认配置里每个成员、主持和裁判的 generation.max_tokens。数值越高，单次回复容量越大，但成本和延迟也可能增加。",
            )
        )

        token_label = QLabel("Token 上限")
        token_label.setObjectName("FieldLabel")
        card.body.addWidget(token_label)

        self.token_limit_spin = QSpinBox()
        self.token_limit_spin.setObjectName("TokenLimitSpin")
        self.token_limit_spin.setRange(1, 200000)
        self.token_limit_spin.setSingleStep(500)
        self.token_limit_spin.setValue(1200)
        self.token_limit_spin.setSuffix(" tokens")
        card.body.addWidget(self.token_limit_spin)

        hint = QLabel("保存会写回当前默认配置文件；正在运行中的讨论不受影响，新启动的讨论会读取新值。")
        hint.setObjectName("FieldHint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        actions = QHBoxLayout()
        actions.setSpacing(TOKENS.spacing.sm)
        self.token_limit_save_button = AppButton("保存 token 上限", tone="secondary")
        self.token_limit_save_button.clicked.connect(self._emit_token_limit_save_request)
        actions.addWidget(self.token_limit_save_button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        self.token_limit_feedback_banner = MessageBanner(tone="info")
        card.body.addWidget(self.token_limit_feedback_banner)
        parent_layout.addWidget(card)

    def _build_manual_models_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "可选模型名称",
                "一行一个模型名。保存后会出现在新建沙盘页的成员模型下拉中，不改写 configs 文件。",
            )
        )

        self.manual_models_input = QPlainTextEdit()
        self.manual_models_input.setPlaceholderText("gpt-5.4-mini\nqwen3.5-plus")
        self.manual_models_input.setMinimumHeight(120)
        self.manual_models_input.setPlainText(
            self._settings.value("manual_model_names", "", str)
        )
        card.body.addWidget(self.manual_models_input)

        actions = QHBoxLayout()
        actions.setSpacing(TOKENS.spacing.sm)
        self.save_manual_models_button = AppButton("保存模型名称", tone="secondary")
        self.save_manual_models_button.clicked.connect(self._save_manual_models)
        actions.addWidget(self.save_manual_models_button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        self.manual_models_banner = MessageBanner(tone="info")
        self.manual_models_banner.set_message(
            "本地生效",
            "这些名称只用于桌面端快速选择；模型是否可调用仍由你的 API Key 和服务商决定。",
            tone="info",
        )
        card.body.addWidget(self.manual_models_banner)
        parent_layout.addWidget(card)

    def _build_stats_card(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="secondary", padding=TOKENS.spacing.lg, spacing=TOKENS.spacing.md)
        card.body.addWidget(SectionHeader("本地概况", "帮助确认桌面端当前可以看到多少配置与历史记录。"))

        stats_row = QHBoxLayout()
        stats_row.setSpacing(TOKENS.spacing.lg)
        self.config_count_block = ValueBlock("可用配置", "0")
        self.session_count_block = ValueBlock("历史 Session", "0")
        stats_row.addWidget(self.config_count_block)
        stats_row.addWidget(self.session_count_block)
        stats_row.addStretch(1)
        card.body.addLayout(stats_row)
        parent_layout.addWidget(card)

    def _emit_default_config(self) -> None:
        self._apply_selected_token_limit()
        config_name = self.default_config_combo.currentData()
        if config_name:
            self.default_config_changed.emit(config_name)

    def _emit_theme_changed(self) -> None:
        theme_key = str(self.theme_combo.currentData() or "")
        if theme_key:
            self.theme_changed.emit(theme_key)

    def _apply_selected_token_limit(self) -> None:
        config_name = str(self.default_config_combo.currentData() or "")
        token_info = self._config_token_limits.get(config_name)
        enabled = token_info is not None
        self.token_limit_spin.setEnabled(enabled)
        self.token_limit_save_button.setEnabled(enabled)
        if not token_info:
            self.token_limit_feedback_banner.set_message(
                "没有可编辑配置",
                "请先在 `configs/` 中提供可用配置，并刷新设置页。",
                tone="warning",
            )
            return

        max_tokens, is_mixed = token_info
        self.token_limit_spin.blockSignals(True)
        self.token_limit_spin.setValue(max_tokens)
        self.token_limit_spin.blockSignals(False)
        if is_mixed:
            self.token_limit_feedback_banner.set_message(
                "当前配置存在多个上限",
                "不同角色的 generation.max_tokens 不一致；保存会统一写入当前输入值。",
                tone="warning",
            )
            return

        self.token_limit_feedback_banner.set_message(
            "保存后对新任务生效",
            "当前值来自默认配置文件；保存后新启动的讨论会使用该上限。",
            tone="info",
        )

    def _emit_token_limit_save_request(self) -> None:
        config_name = str(self.default_config_combo.currentData() or "")
        max_tokens = self.token_limit_spin.value()
        current_tokens, is_mixed = self._config_token_limits.get(config_name, (None, False))
        if current_tokens == max_tokens and not is_mixed:
            self.token_limit_feedback_banner.set_message(
                "无变更",
                "当前 token 上限已经是这个值，不需要重复写入。",
                tone="info",
            )
            return

        self.token_limit_feedback_banner.set_message(
            "正在保存",
            "正在写回当前默认配置文件。",
            tone="info",
        )
        self.token_limit_save_button.set_loading(True, "保存中")
        self.token_limit_save_requested.emit(
            {
                "config_name": config_name,
                "max_tokens": max_tokens,
            }
        )

    def _save_manual_models(self) -> None:
        model_names = self.manual_model_names()
        normalized_text = "\n".join(model_names)
        self.manual_models_input.setPlainText(normalized_text)
        self._settings.setValue("manual_model_names", normalized_text)
        self._settings.sync()
        self.manual_models_banner.set_message(
            "模型名称已保存",
            "新建沙盘页的成员模型下拉已更新。",
            tone="success",
        )
        self.save_manual_models_button.flash_success("已保存")
        self.manual_models_changed.emit(model_names)

    def _apply_provider_preset(self) -> None:
        provider_label = str(self.provider_combo.currentData() or "")
        preset_url = AI_PROVIDER_PRESETS.get(provider_label, "")
        if preset_url:
            self.base_url_input.setText(preset_url)

    def _toggle_api_key_visibility(self) -> None:
        self._api_key_visible = not self._api_key_visible
        self.api_key_input.setEchoMode(QLineEdit.Normal if self._api_key_visible else QLineEdit.Password)
        self.toggle_key_button.set_base_text("隐藏" if self._api_key_visible else "显示")

    def _emit_api_save_request(self) -> None:
        payload = {
            "provider_label": str(self.provider_combo.currentData() or "自定义 OpenAI 兼容接口"),
            "base_url": self.base_url_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
        }
        self.api_feedback_banner.set_message(
            "正在保存",
            "正在写回 `.env` 并同步当前桌面端服务对象。",
            tone="info",
        )
        self.save_api_button.set_loading(True, "保存中")
        self.api_settings_save_requested.emit(payload)

    def _emit_api_connections_test_request(self) -> None:
        connections = self._parse_api_test_lines(self.api_test_input.toPlainText())
        self.api_test_banner.set_message(
            "正在测试",
            "正在顺序测试多组 API 联通性；这不会改写当前正式配置。",
            tone="info",
        )
        self.test_connections_button.set_loading(True, "测试中")
        self.api_connections_test_requested.emit({"connections": connections})

    @staticmethod
    def _parse_api_test_lines(raw_text: str) -> list[dict[str, str]]:
        connections: list[dict[str, str]] = []
        for index, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) < 3:
                connections.append(
                    {
                        "name": f"第 {index} 行",
                        "base_url": "",
                        "api_key": "",
                    }
                )
                continue
            connections.append(
                {
                    "name": parts[0] or f"第 {index} 行",
                    "base_url": parts[1],
                    "api_key": parts[2],
                }
            )
        return connections

    @staticmethod
    def _parse_manual_models(raw_text: str) -> list[str]:
        model_names: list[str] = []
        for raw_line in raw_text.splitlines():
            model_name = raw_line.strip()
            if model_name and model_name not in model_names:
                model_names.append(model_name)
        return model_names
