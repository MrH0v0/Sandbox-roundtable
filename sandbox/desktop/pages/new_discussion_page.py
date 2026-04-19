from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.widgets.common import (
    AppButton,
    AppComboBox,
    CardFrame,
    MessageBanner,
    SectionHeader,
    StatusPill,
    ValueBlock,
    refresh_style,
)
from sandbox.schemas.config import (
    MemberConfigSummary,
    RoundtableConfigSummary,
    SkillCatalogItem,
)


DEFAULT_SKILL_CATEGORIES = [
    "全部",
    "通用",
    "分析",
    "写作",
    "辩论",
    "编程",
    "商业",
    "自定义",
    "未分类",
]


class FieldPanel(QFrame):
    def __init__(
        self,
        title: str,
        hint: str,
        editor: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FieldPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("hovered", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setObjectName("FieldLabel")
        layout.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setObjectName("FieldHint")
        hint_label.setWordWrap(True)
        hint_label.setVisible(bool(hint))
        layout.addWidget(hint_label)

        layout.addWidget(editor)

    def enterEvent(self, event) -> None:
        self.setProperty("hovered", True)
        refresh_style(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hovered", False)
        refresh_style(self)
        super().leaveEvent(event)


class SkillPickerDialog(QDialog):
    skill_selected = Signal(str, str)
    folder_select_requested = Signal(str)

    def __init__(
        self,
        *,
        member_id: str,
        member_name: str,
        skills: list[SkillCatalogItem],
        selected_refs: list[str],
        categories: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.member_id = member_id
        self.visible_skill_refs: list[str] = []
        self._skills = list(skills)
        self._selected_refs = set(selected_refs)

        self.setObjectName("SkillPickerDialog")
        self.setWindowTitle(f"为 {member_name} 添加 skill")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(TOKENS.spacing.sm)

        title = QLabel(f"为 {member_name} 添加 skill")
        title.setObjectName("FieldLabel")
        layout.addWidget(title)

        hint = QLabel("从当前配置的 skill 列表添加，或选择包含 SKILL.md 的完整 skill 文件夹。")
        hint.setObjectName("SubtleText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(TOKENS.spacing.xs)
        folder_row.addStretch(1)
        choose_folder_button = AppButton("选择文件夹", tone="secondary")
        choose_folder_button.clicked.connect(
            lambda _checked=False: self.folder_select_requested.emit(self.member_id)
        )
        folder_row.addWidget(choose_folder_button)
        layout.addLayout(folder_row)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索 skill 名称、ID、文件名")
        self.search_input.textChanged.connect(self._update_results)
        layout.addWidget(self.search_input)

        self.category_combo = AppComboBox()
        for category in categories:
            self.category_combo.addItem(category, category)
        self.category_combo.currentIndexChanged.connect(self._update_results)
        layout.addWidget(self.category_combo)

        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        result_scroll.setMinimumHeight(220)
        result_scroll.setMaximumHeight(320)
        self.result_container = QWidget()
        self.result_layout = QVBoxLayout(self.result_container)
        self.result_layout.setContentsMargins(0, 0, 0, 0)
        self.result_layout.setSpacing(TOKENS.spacing.xs)
        result_scroll.setWidget(self.result_container)
        layout.addWidget(result_scroll)

        self._update_results()

    def mark_skill_added(self, reference: str) -> None:
        self._selected_refs.add(reference)
        self._update_results()

    def _update_results(self) -> None:
        self._clear_result_layout()
        query = self.search_input.text().strip().lower()
        category = self.category_combo.currentData() or "全部"
        matched_skills = []
        for skill in self._skills:
            if category != "全部" and skill.category != category:
                continue
            searchable = " ".join(
                [skill.id, skill.name, skill.source_file, skill.category]
            ).lower()
            if query and query not in searchable:
                continue
            matched_skills.append(skill)

        matched_skills.sort(key=lambda item: (item.category, item.name, item.id))
        self.visible_skill_refs = [skill.source_file for skill in matched_skills]

        if not matched_skills:
            empty_label = QLabel("没有匹配的 skill。")
            empty_label.setObjectName("SubtleText")
            empty_label.setWordWrap(True)
            self.result_layout.addWidget(empty_label)
            return

        for skill in matched_skills:
            self.result_layout.addWidget(self._create_skill_result_row(skill))

    def _create_skill_result_row(self, skill: SkillCatalogItem) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(TOKENS.spacing.xs)

        label = QLabel(NewDiscussionPage._format_skill_label(skill.source_file, skill))
        label.setObjectName("SubtleText")
        label.setWordWrap(True)
        layout.addWidget(label, stretch=1)

        already_added = skill.source_file in self._selected_refs
        button = AppButton("已添加" if already_added else "添加", tone="ghost")
        button.setEnabled(not already_added)
        button.clicked.connect(
            lambda _checked=False, ref=skill.source_file: self.skill_selected.emit(
                self.member_id, ref
            )
        )
        layout.addWidget(button)
        return row

    def _clear_result_layout(self) -> None:
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                while child_layout.count():
                    child_item = child_layout.takeAt(0)
                    child_widget = child_item.widget()
                    if child_widget is not None:
                        child_widget.deleteLater()
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class InlineRenameInput(QLineEdit):
    cancel_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AddMemberDialog(QDialog):
    submitted = Signal(str, str)

    def __init__(
        self,
        *,
        model_names: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新增成员")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(TOKENS.spacing.sm)

        title = QLabel("新增成员")
        title.setObjectName("FieldLabel")
        layout.addWidget(title)

        hint = QLabel("只填写最小必要信息：成员名称和模型。创建后可继续在卡片里配置 skills。")
        hint.setObjectName("SubtleText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        name_label = QLabel("成员名称")
        name_label.setObjectName("FieldLabel")
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：三号成员")
        self.name_input.returnPressed.connect(self._submit)
        layout.addWidget(self.name_input)

        model_label = QLabel("模型")
        model_label.setObjectName("FieldLabel")
        layout.addWidget(model_label)

        self.model_combo = AppComboBox()
        for model_name in model_names:
            self.model_combo.addItem(model_name, model_name)
        layout.addWidget(self.model_combo)

        self.feedback_label = QLabel("")
        self.feedback_label.setObjectName("SubtleText")
        self.feedback_label.setWordWrap(True)
        self.feedback_label.hide()
        layout.addWidget(self.feedback_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(TOKENS.spacing.xs)
        actions.addStretch(1)

        cancel_button = AppButton("取消", tone="ghost")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)

        self.confirm_button = AppButton("新增成员", tone="secondary")
        self.confirm_button.clicked.connect(self._submit)
        actions.addWidget(self.confirm_button)
        layout.addLayout(actions)

    def show_validation_error(self, message: str) -> None:
        self.feedback_label.setText(message)
        self.feedback_label.show()

    def _submit(self) -> None:
        display_name = self.name_input.text().strip()
        model = str(self.model_combo.currentData() or self.model_combo.currentText() or "").strip()
        if not display_name:
            self.show_validation_error("成员名称不能为空。")
            return
        if not model:
            self.show_validation_error("请先选择模型。")
            return
        self.submitted.emit(display_name, model)


class NewDiscussionPage(QWidget):
    start_requested = Signal(dict)
    skill_folder_open_requested = Signal(str)
    skill_folder_select_requested = Signal(str)
    member_add_requested = Signal(str, str, str)
    member_rename_requested = Signal(str, str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self._configs: list[RoundtableConfigSummary] = []
        self._settings = QSettings("sandbox", "roundtable-desktop")
        self.member_model_combos: dict[str, AppComboBox] = {}
        self.open_skill_folder_buttons: dict[str, AppButton] = {}
        self.selected_skill_refs: dict[str, list[str]] = {}
        self._member_model_by_id: dict[str, str] = {}
        self._member_skill_layouts: dict[str, QVBoxLayout] = {}
        self._member_by_id: dict[str, MemberConfigSummary] = {}
        self._skill_catalog_by_ref: dict[str, SkillCatalogItem] = {}
        self._skill_picker_dialog: SkillPickerDialog | None = None
        self._add_member_dialog: AddMemberDialog | None = None
        self._manual_model_names: list[str] = self._load_manual_model_names()
        self._member_name_stacks: dict[str, QStackedLayout] = {}
        self._member_rename_inputs: dict[str, InlineRenameInput] = {}
        self._rename_cancelled_member_ids: set[str] = set()

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

        self._build_hero()
        self._build_body()

    def set_configs(self, configs: list[RoundtableConfigSummary]) -> None:
        self._configs = configs
        current_name = self.config_combo.currentData()
        self.config_combo.blockSignals(True)
        self.config_combo.clear()

        for config in configs:
            self.config_combo.addItem(config.name, config.config_name)

        if current_name:
            index = self.config_combo.findData(current_name)
            if index >= 0:
                self.config_combo.setCurrentIndex(index)
            elif self.config_combo.count() > 0:
                self.config_combo.setCurrentIndex(0)
        elif self.config_combo.count() > 0:
            self.config_combo.setCurrentIndex(0)

        self.config_combo.blockSignals(False)
        self._update_config_summary()

    def set_manual_models(self, model_names: list[str]) -> None:
        self._manual_model_names = self._dedupe_model_names(model_names)
        self._update_config_summary()

    def set_default_config_name(self, config_name: str) -> None:
        if not config_name:
            self._update_config_summary()
            return

        self.config_combo.blockSignals(True)
        index = self.config_combo.findData(config_name)
        if index >= 0:
            self.config_combo.setCurrentIndex(index)
        self.config_combo.blockSignals(False)
        self._update_config_summary()

    def set_busy(self, busy: bool) -> None:
        self.launch_button.set_loading(busy, "启动讨论中")
        self.title_input.setEnabled(not busy)
        self.background_input.setEnabled(not busy)
        self.constraints_input.setEnabled(not busy)
        self.friendly_input.setEnabled(not busy)
        self.enemy_input.setEnabled(not busy)
        self.objectives_input.setEnabled(not busy)
        self.victory_input.setEnabled(not busy)
        self.notes_input.setEnabled(not busy)
        self.config_combo.setEnabled(not busy)
        self.member_config_container.setEnabled(not busy)
        if self._skill_picker_dialog is not None:
            self._skill_picker_dialog.setEnabled(not busy)
        if self._add_member_dialog is not None:
            self._add_member_dialog.setEnabled(not busy)

    def _build_hero(self) -> None:
        hero = CardFrame(variant="hero", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        hero.body.addWidget(
            SectionHeader(
                "新建沙盘",
                "使用说明：先选配置，再填场景，最后启动讨论。",
                eyebrow="Primary Workspace",
                tone="page",
            )
        )

        steps_row = QHBoxLayout()
        steps_row.setSpacing(TOKENS.spacing.sm)
        self.step_config_pill = StatusPill("1. 选择配置", tone="info")
        self.step_scene_pill = StatusPill("2. 填写场景", tone="muted")
        self.step_launch_pill = StatusPill("3. 启动讨论", tone="muted")
        steps_row.addWidget(self.step_config_pill, alignment=Qt.AlignLeft)
        steps_row.addWidget(self.step_scene_pill, alignment=Qt.AlignLeft)
        steps_row.addWidget(self.step_launch_pill, alignment=Qt.AlignLeft)
        steps_row.addStretch(1)
        hero.body.addLayout(steps_row)

        hero_note = QLabel(
            "成员、Moderator 和 Judge 仍由 `configs/` 中现有配置定义。这里不改配置结构，只负责选用和启动。"
        )
        hero_note.setObjectName("SubtleText")
        hero_note.setWordWrap(True)
        hero.body.addWidget(hero_note)
        self.canvas_layout.addWidget(hero)

    def _build_body(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(TOKENS.spacing.lg)
        self.canvas_layout.addLayout(row)

        main_column = QWidget()
        main_column.setObjectName("PageColumn")
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(TOKENS.spacing.lg)
        row.addWidget(main_column, stretch=7)

        side_column = QWidget()
        side_column.setObjectName("SideColumn")
        side_layout = QVBoxLayout(side_column)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(TOKENS.spacing.lg)
        row.addWidget(side_column, stretch=4)

        self._build_primary_form(main_layout)
        self._build_detail_form(main_layout)
        self._build_setup_panel(side_layout)
        side_layout.addStretch(1)

    def _build_primary_form(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        card.body.addWidget(
            SectionHeader(
                "背景",
                "写入主题、背景及约束。避免解释过多。",
            )
        )

        title_block = QWidget()
        title_layout = QVBoxLayout(title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(10)
        title_label = QLabel("主题")
        title_label.setObjectName("FieldLabel")
        title_layout.addWidget(title_label)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("例如：立希武统戴湾")
        title_layout.addWidget(self.title_input)
        card.body.addWidget(title_block)

        self.background_input = QPlainTextEdit()
        self.background_input.setMinimumHeight(190)
        self.background_input.setPlaceholderText("用几段话说明局势、时间窗口、压力来源和当前已知信息。")
        card.body.addWidget(
            FieldPanel(
                "背景描述",
                "以精简的语言让圆桌成员能快速理解这场讨论在解决什么问题。",
                self.background_input,
            )
        )

        self.constraints_input = QPlainTextEdit()
        self.constraints_input.setMinimumHeight(130)
        self.constraints_input.setPlaceholderText("每行一条，例如：48 小时内完成主行动。")
        card.body.addWidget(
            FieldPanel(
                "约束条件",
                "必须满足什么，以及关键的时间或资源边界。",
                self.constraints_input,
            )
        )

        parent_layout.addWidget(card)

    def _build_detail_form(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        card.body.addWidget(
            SectionHeader(
                "已知兵力、目标和胜负条件",
                "！！！这些信息会继续进入同一轮讨论，但它们排在标题、背景和约束之后，避免过载！！！",
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(TOKENS.spacing.md)
        grid.setVerticalSpacing(TOKENS.spacing.md)

        self.friendly_input = self._create_editor("我方兵力 / 资源，每行一条。")
        self.enemy_input = self._create_editor("敌方兵力 / 资源，每行一条。")
        self.objectives_input = self._create_editor("目标，每行一条。")
        self.victory_input = self._create_editor("胜负条件，每行一条。")
        self.notes_input = self._create_editor("额外备注、未证实情报或临时假设，可选。", minimum_height=150)

        grid.addWidget(
            FieldPanel("我方兵力 / 资源", "", self.friendly_input),
            0,
            0,
        )
        grid.addWidget(
            FieldPanel("敌方兵力 / 资源", "突出真正会改变决策的威胁。", self.enemy_input),
            0,
            1,
        )
        grid.addWidget(
            FieldPanel("目标", "", self.objectives_input),
            1,
            0,
        )
        grid.addWidget(
            FieldPanel("胜负条件", "赢的标准，以及不可接受的代价。", self.victory_input),
            1,
            1,
        )
        grid.addWidget(
            FieldPanel("额外备注", "不确定情报、补充限制或需要特别提醒的前提。", self.notes_input),
            2,
            0,
            1,
            2,
        )

        card.body.addLayout(grid)
        parent_layout.addWidget(card)

    def _build_setup_panel(self, parent_layout: QVBoxLayout) -> None:
        card = CardFrame(variant="hero", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        card.body.addWidget(
            SectionHeader(
                "主控台",
                "配置选择、成员概况和启动按钮",
            )
        )

        combo_block = QWidget()
        combo_layout = QVBoxLayout(combo_block)
        combo_layout.setContentsMargins(0, 0, 0, 0)
        combo_layout.setSpacing(10)
        combo_label = QLabel("1. 选择配置文件")
        combo_label.setObjectName("FieldLabel")
        combo_layout.addWidget(combo_label)
        self.config_combo = AppComboBox()
        self.config_combo.currentIndexChanged.connect(self._update_config_summary)
        combo_layout.addWidget(self.config_combo)
        card.body.addWidget(combo_block)

        summary_hint = QLabel("确认这轮讨论会使用哪些成员、谁来主持、谁来裁决。")
        summary_hint.setObjectName("SubtleText")
        summary_hint.setWordWrap(True)
        card.body.addWidget(summary_hint)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(TOKENS.spacing.md)
        metrics.setVerticalSpacing(TOKENS.spacing.sm)
        self.member_count_block = ValueBlock("成员数量")
        self.members_block = ValueBlock("成员概览")
        self.moderator_block = ValueBlock("Moderator")
        self.judge_block = ValueBlock("Judge")
        metrics.addWidget(self.member_count_block, 0, 0)
        metrics.addWidget(self.members_block, 0, 1)
        metrics.addWidget(self.moderator_block, 1, 0)
        metrics.addWidget(self.judge_block, 1, 1)
        card.body.addLayout(metrics)

        member_config_header_row = QHBoxLayout()
        member_config_header_row.setContentsMargins(0, 0, 0, 0)
        member_config_header_row.setSpacing(TOKENS.spacing.xs)
        member_config_header = QLabel("2. 成员模型与 skills")
        member_config_header.setObjectName("FieldLabel")
        member_config_header_row.addWidget(member_config_header)
        member_config_header_row.addStretch(1)
        self.add_member_button = AppButton("新增成员", tone="ghost")
        self.add_member_button.clicked.connect(self._open_add_member_dialog)
        member_config_header_row.addWidget(self.add_member_button)
        card.body.addLayout(member_config_header_row)

        self.member_config_container = QWidget()
        self.member_config_container.setObjectName("MemberConfigContainer")
        self.member_config_layout = QVBoxLayout(self.member_config_container)
        self.member_config_layout.setContentsMargins(0, 0, 0, 0)
        self.member_config_layout.setSpacing(TOKENS.spacing.sm)
        card.body.addWidget(self.member_config_container)

        self.requirements_note = QLabel("启动前最少需要：配置、标题、背景。")
        self.requirements_note.setObjectName("SubtleText")
        self.requirements_note.setWordWrap(True)
        card.body.addWidget(self.requirements_note)

        self.feedback_banner = MessageBanner(tone="info")
        self.feedback_banner.set_message(
            "下一步",
            "先在这里选配置，再回左侧填写场景主叙事，最后直接点击下方按钮启动。",
            tone="info",
        )
        card.body.addWidget(self.feedback_banner)

        self.launch_button = AppButton("开始本轮讨论", tone="primary")
        self.launch_button.clicked.connect(self._submit)
        card.body.addWidget(self.launch_button)

        secondary_note = QLabel("这一步只负责发起讨论。运行状态、结果和历史回放在后续页面查看。")
        secondary_note.setObjectName("SubtleText")
        secondary_note.setWordWrap(True)
        card.body.addWidget(secondary_note)

        parent_layout.addWidget(card)

    def _render_member_config_panel(self, config: RoundtableConfigSummary | None) -> None:
        previous_member_models = dict(self._member_model_by_id)
        self._clear_layout(self.member_config_layout)
        self.member_model_combos.clear()
        self.open_skill_folder_buttons.clear()
        self._member_skill_layouts.clear()
        self._member_name_stacks.clear()
        self._member_rename_inputs.clear()
        self._member_by_id = {}
        self._skill_catalog_by_ref = {}
        self.selected_skill_refs = {}
        self._member_model_by_id = {}
        self._rename_cancelled_member_ids.clear()
        self._close_skill_picker_dialog()

        if config is None:
            empty_label = QLabel("当前没有可用配置。")
            empty_label.setObjectName("SubtleText")
            empty_label.setWordWrap(True)
            self.member_config_layout.addWidget(empty_label)
            return

        self._member_by_id = {member.id: member for member in config.members}
        self._skill_catalog_by_ref = {
            skill.source_file: skill for skill in config.skills
        }

        if not config.members:
            empty_label = QLabel("该配置没有成员可编辑。")
            empty_label.setObjectName("SubtleText")
            self.member_config_layout.addWidget(empty_label)
            return

        for member in config.members:
            model = self._initial_member_model(
                config,
                member,
                previous_model=previous_member_models.get(member.id),
            )
            selected_skills = self._initial_member_skills(config, member, model)
            self._member_model_by_id[member.id] = model
            self.selected_skill_refs[member.id] = selected_skills
            self.member_config_layout.addWidget(
                self._create_member_config_row(config, member, model)
            )
            self._refresh_member_skill_list(member.id)

    def _create_member_config_row(
        self,
        config: RoundtableConfigSummary,
        member: MemberConfigSummary,
        model: str,
    ) -> QFrame:
        row = QFrame()
        row.setObjectName("MiniPanel")
        row.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(TOKENS.spacing.sm)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(TOKENS.spacing.sm)

        name_host = QWidget()
        name_stack = QStackedLayout(name_host)
        name_stack.setContentsMargins(0, 0, 0, 0)

        display_widget = QWidget()
        display_layout = QHBoxLayout(display_widget)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(TOKENS.spacing.xs)
        name_label = QLabel(member.display_name)
        name_label.setObjectName("MetricValue")
        name_label.setWordWrap(True)
        display_layout.addWidget(name_label, stretch=1)
        rename_button = AppButton("改名", tone="ghost")
        rename_button.clicked.connect(
            lambda _checked=False, member_id=member.id: self._start_member_rename(member_id)
        )
        display_layout.addWidget(rename_button)

        edit_widget = QWidget()
        edit_layout = QHBoxLayout(edit_widget)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        edit_layout.setSpacing(TOKENS.spacing.xs)
        rename_input = InlineRenameInput(member.display_name)
        rename_input.setPlaceholderText("输入成员名称")
        rename_input.returnPressed.connect(
            lambda member_id=member.id: self._submit_member_rename(member_id)
        )
        rename_input.editingFinished.connect(
            lambda member_id=member.id: self._handle_member_rename_finished(member_id)
        )
        rename_input.cancel_requested.connect(
            lambda member_id=member.id: self._cancel_member_rename(member_id)
        )
        edit_layout.addWidget(rename_input, stretch=1)
        save_button = AppButton("保存", tone="secondary")
        save_button.clicked.connect(
            lambda _checked=False, member_id=member.id: self._submit_member_rename(member_id)
        )
        edit_layout.addWidget(save_button)
        cancel_button = AppButton("取消", tone="ghost")
        cancel_button.clicked.connect(
            lambda _checked=False, member_id=member.id: self._cancel_member_rename(member_id)
        )
        edit_layout.addWidget(cancel_button)

        name_stack.addWidget(display_widget)
        name_stack.addWidget(edit_widget)
        name_stack.setCurrentWidget(display_widget)
        self._member_name_stacks[member.id] = name_stack
        self._member_rename_inputs[member.id] = rename_input

        title_row.addWidget(name_host, stretch=1)

        combo = AppComboBox()
        combo.setMinimumWidth(150)
        available_models = self._available_models_for_config(config, member)
        if available_models:
            for available_model in available_models:
                combo.addItem(available_model, available_model)
            index = combo.findData(model)
            combo.setCurrentIndex(index if index >= 0 else 0)
        else:
            combo.addItem("无可用模型", "")
            combo.setEnabled(False)

        combo.currentIndexChanged.connect(
            lambda _index, member_id=member.id: self._handle_member_model_changed(member_id)
        )
        self.member_model_combos[member.id] = combo
        title_row.addWidget(combo)
        layout.addLayout(title_row)

        skills_label = QLabel("已选 skills")
        skills_label.setObjectName("FieldLabel")
        layout.addWidget(skills_label)

        skill_list = QVBoxLayout()
        skill_list.setContentsMargins(0, 0, 0, 0)
        skill_list.setSpacing(6)
        self._member_skill_layouts[member.id] = skill_list
        layout.addLayout(skill_list)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(TOKENS.spacing.xs)
        add_button = AppButton("添加 skill", tone="secondary")
        add_button.clicked.connect(
            lambda _checked=False, member_id=member.id: self._open_skill_picker(member_id)
        )
        actions.addWidget(add_button, stretch=1)

        open_folder_button = AppButton("打开文件夹", tone="ghost")
        open_folder_button.clicked.connect(
            lambda _checked=False, member_id=member.id: self._request_skill_folder_open(member_id)
        )
        self.open_skill_folder_buttons[member.id] = open_folder_button
        actions.addWidget(open_folder_button)
        layout.addLayout(actions)
        return row

    def _open_add_member_dialog(self) -> None:
        config = self._current_config()
        if config is None:
            self.feedback_banner.set_message(
                "先选择配置",
                "新增成员前需要先确定当前使用的是哪一份配置文件。",
                tone="warning",
            )
            return

        self._close_add_member_dialog()
        model_names = self._dedupe_model_names([*config.available_models, *self._manual_model_names])
        dialog = AddMemberDialog(model_names=model_names, parent=self)
        dialog.submitted.connect(self._submit_new_member)
        dialog.finished.connect(lambda _result, current=dialog: self._clear_add_member_dialog(current))
        self._add_member_dialog = dialog
        dialog.open()

    def _submit_new_member(self, display_name: str, model: str) -> None:
        config = self._current_config()
        if config is None:
            return

        cleaned_name = str(display_name or "").strip()
        cleaned_model = str(model or "").strip()
        if not cleaned_name:
            if self._add_member_dialog is not None:
                self._add_member_dialog.show_validation_error("成员名称不能为空。")
            return
        if not cleaned_model:
            if self._add_member_dialog is not None:
                self._add_member_dialog.show_validation_error("请先选择模型。")
            return
        if cleaned_name in {member.display_name for member in config.members}:
            if self._add_member_dialog is not None:
                self._add_member_dialog.show_validation_error("当前配置里已经存在同名成员。")
            return

        self.member_add_requested.emit(config.config_name, cleaned_name, cleaned_model)
        self._close_add_member_dialog()

    def _close_add_member_dialog(self) -> None:
        if self._add_member_dialog is not None:
            self._add_member_dialog.close()
            self._add_member_dialog = None

    def _clear_add_member_dialog(self, dialog: AddMemberDialog) -> None:
        if self._add_member_dialog is dialog:
            self._add_member_dialog = None

    def _start_member_rename(self, member_id: str) -> None:
        name_stack = self._member_name_stacks.get(member_id)
        rename_input = self._member_rename_inputs.get(member_id)
        member = self._member_by_id.get(member_id)
        if name_stack is None or rename_input is None or member is None:
            return
        rename_input.setText(member.display_name)
        name_stack.setCurrentIndex(1)
        rename_input.setFocus(Qt.OtherFocusReason)
        rename_input.selectAll()

    def _cancel_member_rename(self, member_id: str) -> None:
        self._rename_cancelled_member_ids.add(member_id)
        name_stack = self._member_name_stacks.get(member_id)
        if name_stack is not None:
            name_stack.setCurrentIndex(0)

    def _handle_member_rename_finished(self, member_id: str) -> None:
        if member_id in self._rename_cancelled_member_ids:
            self._rename_cancelled_member_ids.discard(member_id)
            return
        self._submit_member_rename(member_id)

    def _submit_member_rename(self, member_id: str, display_name: str | None = None) -> None:
        config = self._current_config()
        rename_input = self._member_rename_inputs.get(member_id)
        member = self._member_by_id.get(member_id)
        name_stack = self._member_name_stacks.get(member_id)
        if config is None or member is None or name_stack is None:
            return

        next_name = str(display_name if display_name is not None else rename_input.text() if rename_input is not None else "").strip()
        if not next_name:
            self.feedback_banner.set_message(
                "成员名称不能为空",
                "请为该成员提供一个可识别的展示名称。",
                tone="warning",
            )
            if rename_input is not None:
                rename_input.setFocus(Qt.OtherFocusReason)
            return
        if next_name in {
            current_member.display_name
            for current_member in config.members
            if current_member.id != member_id
        }:
            self.feedback_banner.set_message(
                "成员名称重复",
                "当前配置里已经存在同名成员，请换一个名称。",
                tone="warning",
            )
            if rename_input is not None:
                rename_input.setFocus(Qt.OtherFocusReason)
                rename_input.selectAll()
            return

        if next_name == member.display_name:
            name_stack.setCurrentIndex(0)
            return

        self.member_rename_requested.emit(config.config_name, member_id, next_name)
        name_stack.setCurrentIndex(0)

    def _skill_categories_for_config(self, config: RoundtableConfigSummary) -> list[str]:
        categories = list(DEFAULT_SKILL_CATEGORIES)
        for skill in config.skills:
            if skill.category not in categories:
                categories.append(skill.category)
        return categories

    def _open_skill_picker(self, member_id: str) -> None:
        config = self._current_config()
        member = self._member_by_id.get(member_id)
        if config is None or member is None:
            return

        self._close_skill_picker_dialog()
        dialog = SkillPickerDialog(
            member_id=member_id,
            member_name=member.display_name,
            skills=list(self._skill_catalog_by_ref.values()),
            selected_refs=list(self.selected_skill_refs.get(member_id, [])),
            categories=self._skill_categories_for_config(config),
            parent=self,
        )
        dialog.skill_selected.connect(self._add_skill_from_dialog)
        dialog.folder_select_requested.connect(self._request_skill_folder_select)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_skill_picker_dialog(current)
        )
        self._skill_picker_dialog = dialog
        dialog.open()

    def _request_skill_folder_open(self, member_id: str) -> None:
        self.skill_folder_open_requested.emit(member_id)

    def _request_skill_folder_select(self, member_id: str) -> None:
        self.skill_folder_select_requested.emit(member_id)

    def _add_skill_from_dialog(self, member_id: str, reference: str) -> None:
        added = self._add_skill_to_member(member_id, reference)
        dialog = self._skill_picker_dialog
        if added and dialog is not None and dialog.member_id == member_id:
            dialog.mark_skill_added(reference)
            dialog.accept()

    def _close_skill_picker_dialog(self) -> None:
        if self._skill_picker_dialog is not None:
            self._skill_picker_dialog.close()
            self._skill_picker_dialog = None

    def _clear_skill_picker_dialog(self, dialog: SkillPickerDialog) -> None:
        if self._skill_picker_dialog is dialog:
            self._skill_picker_dialog = None

    def add_external_skill_folder(self, member_id: str, folder_path: str) -> bool:
        path = Path(folder_path)
        if not path.is_dir() or not (path / "SKILL.md").is_file():
            self.feedback_banner.set_message(
                "无法添加 skill 文件夹",
                f"请选择包含 SKILL.md 的文件夹：{folder_path}",
                tone="warning",
            )
            return False

        reference = str(path)
        self._skill_catalog_by_ref[reference] = SkillCatalogItem(
            id=path.name,
            name=path.name,
            category="自定义",
            source_file=reference,
        )
        added = self._add_skill_to_member(member_id, reference)
        if added:
            self.feedback_banner.set_message(
                "已添加 skill 文件夹",
                f"{path.name} 将连同 references / scripts 一起用于该成员。",
                tone="success",
            )
            dialog = self._skill_picker_dialog
            if dialog is not None and dialog.member_id == member_id:
                dialog.accept()
        return added

    def show_skill_folder_select_cancelled(self, *, member_name: str) -> None:
        self.feedback_banner.set_message(
            "已取消添加 skill",
            f"没有为 {member_name} 添加新的 skill 文件夹。",
            tone="info",
        )

    def show_skill_folder_open_feedback(
        self,
        *,
        member_name: str,
        folder_path: str,
        success: bool,
    ) -> None:
        if success:
            self.feedback_banner.set_message(
                "已打开 skills 文件夹",
                f"{member_name} 使用同一个 skills 目录：{folder_path}",
                tone="success",
            )
            return

        self.feedback_banner.set_message(
            "无法打开 skills 文件夹",
            f"{member_name} 对应的 skills 目录不可用：{folder_path or '未配置'}",
            tone="warning",
        )

    def show_member_added_feedback(self, *, member_name: str) -> None:
        self.feedback_banner.set_message(
            "成员已新增",
            f"{member_name} 已加入当前配置，现在可以继续选择模型和添加 skills。",
            tone="success",
        )

    def show_member_renamed_feedback(self, *, member_name: str) -> None:
        self.feedback_banner.set_message(
            "成员名称已更新",
            f"当前成员已更名为 {member_name}。",
            tone="success",
        )

    def _refresh_member_skill_list(self, member_id: str) -> None:
        layout = self._member_skill_layouts.get(member_id)
        if layout is None:
            return

        self._clear_layout(layout)
        selected_refs = self.selected_skill_refs.get(member_id, [])
        if not selected_refs:
            empty_label = QLabel("未绑定 skill。")
            empty_label.setObjectName("SubtleText")
            empty_label.setWordWrap(True)
            layout.addWidget(empty_label)
            return

        for reference in selected_refs:
            layout.addWidget(self._create_selected_skill_row(member_id, reference))

    def _create_selected_skill_row(self, member_id: str, reference: str) -> QWidget:
        skill = self._resolve_skill(reference)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(TOKENS.spacing.xs)

        label = QLabel(self._format_skill_label(reference, skill))
        label.setObjectName("SubtleText")
        label.setWordWrap(True)
        layout.addWidget(label, stretch=1)

        remove_button = AppButton("移除", tone="ghost")
        remove_button.clicked.connect(
            lambda _checked=False, ref=reference, mid=member_id: self._remove_skill_from_member(mid, ref)
        )
        layout.addWidget(remove_button)
        return row

    def _handle_member_model_changed(self, member_id: str) -> None:
        config = self._current_config()
        member = self._member_by_id.get(member_id)
        combo = self.member_model_combos.get(member_id)
        if config is None or member is None or combo is None:
            return

        previous_model = self._member_model_by_id.get(member_id)
        if previous_model:
            self._persist_member_binding(config.config_name, member_id, previous_model)

        next_model = str(combo.currentData() or combo.currentText() or "").strip()
        self._member_model_by_id[member_id] = next_model
        stored_skills = self._load_member_binding(config.config_name, member_id, next_model)
        if stored_skills is None and next_model == member.model:
            stored_skills = member.skills
        self.selected_skill_refs[member_id] = self._dedupe_skill_refs(stored_skills or [])
        self._refresh_member_skill_list(member_id)
        self._close_skill_picker_dialog()
        if next_model:
            self.feedback_banner.set_message(
                "已切换模型",
                f"{member.display_name} 当前使用 {next_model}，skills 已按该模型刷新。",
                tone="info",
            )

    def _add_skill_to_member(self, member_id: str, reference: str) -> bool:
        selected_refs = self.selected_skill_refs.setdefault(member_id, [])
        if reference in selected_refs:
            self.feedback_banner.set_message("skill 已存在", "该成员已经添加过这个 skill。", tone="warning")
            return False

        selected_refs.append(reference)
        self._persist_current_member_binding(member_id)
        self._refresh_member_skill_list(member_id)
        skill = self._resolve_skill(reference)
        self.feedback_banner.set_message(
            "已添加 skill",
            self._format_skill_label(reference, skill),
            tone="success",
        )
        return True

    def _remove_skill_from_member(self, member_id: str, reference: str) -> None:
        selected_refs = self.selected_skill_refs.setdefault(member_id, [])
        self.selected_skill_refs[member_id] = [
            item for item in selected_refs if item != reference
        ]
        self._persist_current_member_binding(member_id)
        self._refresh_member_skill_list(member_id)
        self.feedback_banner.set_message("已移除 skill", reference, tone="info")

    def _initial_member_model(
        self,
        config: RoundtableConfigSummary,
        member: MemberConfigSummary,
        *,
        previous_model: str | None = None,
    ) -> str:
        if previous_model and previous_model in self._available_models_for_config(config, member):
            return previous_model
        if member.model:
            return member.model
        available_models = self._available_models_for_config(config, member)
        return available_models[0] if available_models else ""

    def _initial_member_skills(
        self,
        config: RoundtableConfigSummary,
        member: MemberConfigSummary,
        model: str,
    ) -> list[str]:
        stored_skills = self._load_member_binding(config.config_name, member.id, model)
        if stored_skills is not None:
            return self._dedupe_skill_refs(stored_skills)
        return self._dedupe_skill_refs(member.skills if model == member.model else [])

    def _build_member_overrides(self) -> list[dict[str, object]]:
        overrides: list[dict[str, object]] = []
        config = self._current_config()
        if config is None:
            return overrides

        for member in config.members:
            model = self._current_member_model(member.id)
            overrides.append(
                {
                    "member_id": member.id,
                    "model": model,
                    "skills": list(self.selected_skill_refs.get(member.id, [])),
                }
            )
        return overrides

    def _available_models_for_config(
        self,
        config: RoundtableConfigSummary,
        member: MemberConfigSummary,
    ) -> list[str]:
        return self._dedupe_model_names(
            [member.model, *config.available_models, *self._manual_model_names]
        )

    def _current_member_model(self, member_id: str) -> str:
        combo = self.member_model_combos.get(member_id)
        if combo is None:
            return self._member_model_by_id.get(member_id, "")
        return str(combo.currentData() or combo.currentText() or "").strip()

    def _persist_current_member_binding(self, member_id: str) -> None:
        config = self._current_config()
        model = self._current_member_model(member_id)
        if config is None or not model:
            return
        self._persist_member_binding(config.config_name, member_id, model)

    def _persist_member_binding(self, config_name: str, member_id: str, model: str) -> None:
        key = self._binding_key(config_name, member_id, model)
        value = json.dumps(self.selected_skill_refs.get(member_id, []), ensure_ascii=False)
        self._settings.setValue(key, value)

    def _load_member_binding(
        self,
        config_name: str,
        member_id: str,
        model: str,
    ) -> list[str] | None:
        if not model:
            return None

        raw_value = self._settings.value(
            self._binding_key(config_name, member_id, model),
            "",
            str,
        )
        if not raw_value:
            return None

        try:
            payload = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, list):
            return None
        return self._dedupe_skill_refs([str(item) for item in payload])

    @staticmethod
    def _binding_key(config_name: str, member_id: str, model: str) -> str:
        safe_model = model.replace("/", "_")
        return f"member_skill_bindings/{config_name}/{member_id}/{safe_model}"

    def _resolve_skill(self, reference: str) -> SkillCatalogItem | None:
        if reference in self._skill_catalog_by_ref:
            return self._skill_catalog_by_ref[reference]
        for skill in self._skill_catalog_by_ref.values():
            if skill.id == reference:
                return skill
        return None

    @staticmethod
    def _format_skill_label(reference: str, skill: SkillCatalogItem | None) -> str:
        if skill is None:
            return f"{reference} · 未分类"
        leaf_name = skill.source_file.replace("\\", "/").rsplit("/", 1)[-1]
        if Path(skill.source_file).is_absolute() or "." not in leaf_name:
            return f"{skill.name} · {skill.category} · 文件夹"
        return f"{skill.name} · {skill.category}"

    @staticmethod
    def _dedupe_skill_refs(references: list[str]) -> list[str]:
        deduped: list[str] = []
        for reference in references:
            cleaned = str(reference).strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    def _load_manual_model_names(self) -> list[str]:
        raw_value = self._settings.value("manual_model_names", "", str)
        return self._dedupe_model_names(str(raw_value).splitlines())

    @staticmethod
    def _dedupe_model_names(model_names: list[str]) -> list[str]:
        deduped: list[str] = []
        for model_name in model_names:
            cleaned = str(model_name).strip()
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                NewDiscussionPage._clear_layout(child_layout)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _update_config_summary(self) -> None:
        config = self._current_config()
        if config is None:
            self.member_count_block.set_value("未选择")
            self.members_block.set_value("当前没有可用配置。")
            self.moderator_block.set_value("-")
            self.judge_block.set_value("-")
            self.step_config_pill.set_tone("warning")
            self._render_member_config_panel(None)
            return

        self.member_count_block.set_value(str(config.member_count))
        self.members_block.set_value(" / ".join(config.member_names))
        self.moderator_block.set_value(config.moderator_name)
        self.judge_block.set_value(config.judge_name)
        self.step_config_pill.set_tone("success")
        self._render_member_config_panel(config)

    def _submit(self) -> None:
        config = self._current_config()
        if config is None:
            self.feedback_banner.set_message("先选择配置", "右侧先选一个可用配置，再启动讨论。", tone="warning")
            self.step_config_pill.set_tone("warning")
            return

        missing_model_members = [
            member.display_name
            for member in config.members
            if not self._current_member_model(member.id)
        ]
        if missing_model_members:
            self.feedback_banner.set_message(
                "缺少成员模型",
                " / ".join(missing_model_members),
                tone="warning",
            )
            return

        if not self.title_input.text().strip():
            self.feedback_banner.set_message("先填写标题", "标题是最短的场景锚点，补上后再启动。", tone="warning")
            self.step_scene_pill.set_tone("warning")
            return

        if not self.background_input.toPlainText().strip():
            self.feedback_banner.set_message("先填写背景", "背景描述是首轮判断的主要输入，不能为空。", tone="warning")
            self.step_scene_pill.set_tone("warning")
            return

        self.step_scene_pill.set_tone("success")
        self.step_launch_pill.set_tone("success")
        self.feedback_banner.set_message(
            "讨论已提交",
            "正在切换到运行状态页，后台会继续执行完整讨论流程。",
            tone="success",
        )
        self.start_requested.emit(
            {
                "config_name": self.config_combo.currentData(),
                "title": self.title_input.text(),
                "background": self.background_input.toPlainText(),
                "constraints": self.constraints_input.toPlainText(),
                "friendly_forces": self.friendly_input.toPlainText(),
                "enemy_forces": self.enemy_input.toPlainText(),
                "objectives": self.objectives_input.toPlainText(),
                "victory_conditions": self.victory_input.toPlainText(),
                "additional_notes": self.notes_input.toPlainText(),
                "member_overrides": self._build_member_overrides(),
            }
        )

    def _current_config(self) -> RoundtableConfigSummary | None:
        current_name = self.config_combo.currentData()
        for config in self._configs:
            if config.config_name == current_name:
                return config
        return None

    @staticmethod
    def _create_editor(placeholder: str, *, minimum_height: int = 140) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setPlaceholderText(placeholder)
        editor.setMinimumHeight(minimum_height)
        return editor
