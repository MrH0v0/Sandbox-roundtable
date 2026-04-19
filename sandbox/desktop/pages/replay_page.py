from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.theme import (
    build_markdown_document_css,
    get_status_text,
    get_status_tone,
    normalize_status,
)
from sandbox.desktop.widgets.common import (
    ActivityBar,
    AnimatedStackedWidget,
    AppButton,
    CardFrame,
    ContextBadge,
    EmptyStateWidget,
    HistoryItemWidget,
    SectionHeader,
    StatusPill,
    ValueBlock,
    attach_list_item_widget,
)
from sandbox.renderers.markdown import session_markdown_for_display
from sandbox.renderers.session_export import (
    get_export_markdown_for_session,
    get_export_text_for_session,
    suggest_session_export_filename,
)
from sandbox.schemas.discussion import SessionRecord, SessionSummary


class ReplayPage(QWidget):
    session_selected = Signal(str)
    session_delete_requested = Signal(str)
    open_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self._current_session_id: str | None = None
        self._history_widgets: dict[str, HistoryItemWidget] = {}
        self._preview_session: SessionRecord | None = None
        self._preview_markdown_text = ""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("PageScrollArea")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root_layout.addWidget(self.page_scroll)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("PageCanvas")
        self.page_scroll.setWidget(self.scroll_content)

        layout = QVBoxLayout(self.scroll_content)
        layout.setContentsMargins(0, 0, 0, TOKENS.spacing.xxl)
        layout.setSpacing(TOKENS.spacing.lg)

        hero = CardFrame(variant="hero", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        hero.body.addWidget(
            SectionHeader(
                "Session 回放",
                "这里专门用于复盘历史 session。先读摘要、确认来源和配置，再决定是否导出或是于结果页打开。",
                eyebrow="History",
                tone="page",
            )
        )

        hero_row = QHBoxLayout()
        hero_row.setSpacing(TOKENS.spacing.lg)
        self.history_count_block = ValueBlock("历史记录", "0")
        self.selection_block = ValueBlock("当前预览", "未选择")
        self.storage_block = ValueBlock("查看方式", "本地 Session 存储")
        hero_row.addWidget(self.history_count_block)
        hero_row.addWidget(self.selection_block, stretch=2)
        hero_row.addWidget(self.storage_block)
        hero_row.addStretch(1)
        self.source_status = StatusPill("历史回放", tone="warning")
        hero_row.addWidget(self.source_status, alignment=Qt.AlignTop)
        self.selection_status = StatusPill("等待中", tone="muted")
        hero_row.addWidget(self.selection_status, alignment=Qt.AlignTop)
        hero.body.addLayout(hero_row)
        layout.addWidget(hero)

        body_row = QHBoxLayout()
        body_row.setSpacing(TOKENS.spacing.lg)
        layout.addLayout(body_row, stretch=1)

        self.left_card = CardFrame(variant="secondary", padding=TOKENS.spacing.lg, spacing=TOKENS.spacing.md)
        self.left_card.setFixedWidth(420)
        body_row.addWidget(self.left_card)
        self._build_list_panel()

        self.preview_stack = AnimatedStackedWidget()
        body_row.addWidget(self.preview_stack, stretch=1)

        self.preview_empty = EmptyStateWidget(
            "还没有预览内容",
            "从左侧选择一个历史 session。右侧会先展示适合阅读的复盘摘要，而不是直接把整份结构化数据铺开。",
        )
        self.preview_stack.addWidget(self.preview_empty)

        self.preview_content = QWidget()
        self.preview_content.setObjectName("PageCanvas")
        self.preview_stack.addWidget(self.preview_content)
        self._build_preview_panel()
        self.preview_stack.setCurrentWidget(self.preview_empty)

    def set_sessions(self, sessions: list[SessionSummary]) -> None:
        current_id = self._current_session_id
        self._history_widgets.clear()
        self.session_list.blockSignals(True)
        self.session_list.clear()

        for summary in sessions:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, summary.session_id)
            widget = HistoryItemWidget(
                title=summary.title,
                meta=self._build_meta(summary),
                status=normalize_status(summary.status, default="completed"),
            )
            widget.clicked.connect(lambda session_id=summary.session_id: self._select_session(session_id))
            widget.delete_requested.connect(
                lambda session_id=summary.session_id: self.session_delete_requested.emit(session_id)
            )
            attach_list_item_widget(self.session_list, item, widget)
            self._history_widgets[summary.session_id] = widget

        self.session_list.blockSignals(False)
        self.history_count_block.set_value(str(len(sessions)))

        if not sessions:
            self.list_stack.setCurrentWidget(self.list_empty)
            self._show_empty_preview()
            return

        self.list_stack.setCurrentWidget(self.session_list)
        session_id = current_id if current_id and current_id in self._history_widgets else sessions[0].session_id
        self._select_session(session_id)

    def set_preview_session(self, session: SessionRecord | None) -> None:
        self._preview_session = session
        if session is None:
            self._show_empty_preview()
            return

        session_status = normalize_status(getattr(session.status, "value", session.status), default="completed")
        status_text = get_status_text(session_status, default="completed")
        status_tone = get_status_tone(session_status, default="muted")

        self._current_session_id = session.session_id
        self._sync_history_selection()
        self.preview_stack.setCurrentWidget(self.preview_content)

        self.preview_title.set_value(session.scenario.title)
        self.preview_config.set_value(session.config_name)
        self.preview_session_id.set_value(session.session_id)
        self.preview_rounds.set_value(str(len(session.rounds)))
        self.preview_time.set_value(self._format_time(session.completed_at or session.created_at))
        self.selection_block.set_value(session.scenario.title)
        self.selection_status.setText(status_text)
        self.selection_status.set_tone(status_tone)
        self.preview_status.setText(status_text)
        self.preview_status.set_tone(status_tone)
        self.preview_activity.hide()
        self.open_button.setEnabled(True)
        self.copy_id_button.setEnabled(True)
        self.copy_summary_button.setEnabled(True)
        self.export_markdown_button.setEnabled(True)
        self.export_text_button.setEnabled(True)

        self.context_source.set_value("历史回放")
        self.context_status.set_value(status_text)
        self.context_config.set_value(session.config_name)
        self.context_session.set_value(session.session_id)
        self.context_rounds.set_value(f"{len(session.rounds)} 个阶段")
        self.context_title.set_value(session.scenario.title)

        markdown_text = session_markdown_for_display(session).strip() or "# 空结果\n该 session 暂无 Markdown 内容。"
        self._preview_markdown_text = markdown_text
        self.preview_markdown.setMarkdown(markdown_text)

    def _build_list_panel(self) -> None:
        self.left_card.body.addWidget(
            SectionHeader(
                "历史记录",
                "按最近更新时间倒序展示。这里负责选中和切换历史 session，右侧负责阅读和复盘动作。",
            )
        )

        toolbar = QHBoxLayout()
        toolbar.setSpacing(TOKENS.spacing.sm)
        toolbar.addStretch(1)
        refresh_button = AppButton("刷新列表", tone="ghost")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(refresh_button)
        self.left_card.body.addLayout(toolbar)

        self.list_feedback_label = QLabel("")
        self.list_feedback_label.setObjectName("SubtleText")
        self.list_feedback_label.setWordWrap(True)
        self.left_card.body.addWidget(self.list_feedback_label)

        self.list_stack = AnimatedStackedWidget()
        self.left_card.body.addWidget(self.list_stack, stretch=1)

        self.list_empty = EmptyStateWidget(
            "还没有历史 session",
            "运行至少一轮讨论后，这里会显示本地已落盘的 session 记录。",
        )
        self.list_stack.addWidget(self.list_empty)

        self.session_list = QListWidget()
        self.session_list.setObjectName("SessionHistoryList")
        self.session_list.setSpacing(0)
        self.session_list.currentItemChanged.connect(self._handle_selection)
        self.list_stack.addWidget(self.session_list)
        self.list_stack.setCurrentWidget(self.list_empty)

    def _build_preview_panel(self) -> None:
        layout = QVBoxLayout(self.preview_content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(TOKENS.spacing.lg)

        meta_card = CardFrame(variant="secondary", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        meta_card.body.addWidget(
            SectionHeader(
                "复盘工具条",
                "先确认这份历史记录属于哪次讨论，再决定复制摘要、复制 Session ID，或把它打开到结果页继续细看。",
            )
        )

        context_grid = QGridLayout()
        context_grid.setHorizontalSpacing(TOKENS.spacing.md)
        context_grid.setVerticalSpacing(TOKENS.spacing.md)
        self.context_source = ContextBadge("来源")
        self.context_status = ContextBadge("状态")
        self.context_config = ContextBadge("配置")
        self.context_session = ContextBadge("Session")
        self.context_rounds = ContextBadge("阶段")
        self.context_title = ContextBadge("标题")
        context_grid.addWidget(self.context_source, 0, 0)
        context_grid.addWidget(self.context_status, 0, 1)
        context_grid.addWidget(self.context_config, 0, 2)
        context_grid.addWidget(self.context_session, 1, 0)
        context_grid.addWidget(self.context_rounds, 1, 1)
        context_grid.addWidget(self.context_title, 1, 2)
        meta_card.body.addLayout(context_grid)

        info_row = QHBoxLayout()
        info_row.setSpacing(TOKENS.spacing.lg)
        self.preview_title = ValueBlock("场景")
        self.preview_config = ValueBlock("配置")
        self.preview_session_id = ValueBlock("Session ID")
        self.preview_rounds = ValueBlock("阶段数")
        self.preview_time = ValueBlock("完成时间")
        info_row.addWidget(self.preview_title, stretch=2)
        info_row.addWidget(self.preview_config)
        info_row.addWidget(self.preview_session_id, stretch=2)
        info_row.addWidget(self.preview_rounds)
        info_row.addWidget(self.preview_time)
        meta_card.body.addLayout(info_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(TOKENS.spacing.sm)

        status_title = QLabel("预览状态")
        status_title.setObjectName("MetricTitle")
        action_row.addWidget(status_title)
        self.preview_status = StatusPill("等待中", tone="muted")
        action_row.addWidget(self.preview_status)

        self.preview_activity = ActivityBar()
        action_row.addWidget(self.preview_activity)
        action_row.addStretch(1)

        self.copy_summary_button = AppButton("复制复盘摘要", tone="secondary")
        self.copy_summary_button.setEnabled(False)
        self.copy_summary_button.clicked.connect(self._copy_summary)
        action_row.addWidget(self.copy_summary_button)

        self.copy_id_button = AppButton("复制 Session ID", tone="ghost")
        self.copy_id_button.setEnabled(False)
        self.copy_id_button.clicked.connect(self._copy_session_id)
        action_row.addWidget(self.copy_id_button)

        self.export_markdown_button = AppButton("导出 Markdown", tone="secondary")
        self.export_markdown_button.setEnabled(False)
        self.export_markdown_button.clicked.connect(lambda: self._export_session("markdown"))
        action_row.addWidget(self.export_markdown_button)

        self.export_text_button = AppButton("导出 TXT", tone="ghost")
        self.export_text_button.setEnabled(False)
        self.export_text_button.clicked.connect(lambda: self._export_session("text"))
        action_row.addWidget(self.export_text_button)

        self.open_button = AppButton("在结果页打开历史回放", tone="secondary")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_requested.emit)
        action_row.addWidget(self.open_button)
        meta_card.body.addLayout(action_row)
        self.export_feedback_label = QLabel("")
        self.export_feedback_label.setObjectName("SubtleText")
        self.export_feedback_label.setWordWrap(True)
        meta_card.body.addWidget(self.export_feedback_label)
        layout.addWidget(meta_card)

        self.reading_card = CardFrame(variant="reading", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        self.reading_card.setMinimumHeight(420)
        self.reading_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.reading_card.body.addWidget(
            SectionHeader(
                "复盘摘要",
                "这里默认展示最适合先读的 Markdown 摘要。需要更完整的上下文时，再打开到结果页继续查看。",
            )
        )
        self.preview_markdown = QTextBrowser()
        self.preview_markdown.setObjectName("ReplayPreview")
        self.preview_markdown.setMinimumHeight(340)
        self.preview_markdown.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_markdown.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_markdown.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_markdown.document().setDefaultStyleSheet(build_markdown_document_css())
        self.preview_markdown.document().setDocumentMargin(TOKENS.spacing.md)
        self.reading_card.body.addWidget(self.preview_markdown)
        layout.addWidget(self.reading_card)

    def refresh_theme(self, theme_key: str | None = None) -> None:
        self.preview_markdown.document().setDefaultStyleSheet(build_markdown_document_css(theme_key))
        if self._preview_markdown_text:
            self.preview_markdown.setMarkdown(self._preview_markdown_text)

    def _handle_selection(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if previous is not None:
            previous_widget = self.session_list.itemWidget(previous)
            if isinstance(previous_widget, HistoryItemWidget):
                previous_widget.set_selected(False)

        if current is None:
            self._show_empty_preview()
            return

        current_widget = self.session_list.itemWidget(current)
        if isinstance(current_widget, HistoryItemWidget):
            current_widget.set_selected(True)

        session_id = current.data(Qt.UserRole)
        if not session_id:
            self._show_empty_preview()
            return

        self._current_session_id = str(session_id)
        loading_text = get_status_text("loading")
        loading_tone = get_status_tone("loading")
        self._preview_session = None
        self.selection_block.set_value("正在读取...")
        self.selection_status.setText(loading_text)
        self.selection_status.set_tone(loading_tone)
        self.preview_status.setText(loading_text)
        self.preview_status.set_tone(loading_tone)
        self.preview_activity.show()
        self.open_button.setEnabled(False)
        self.copy_id_button.setEnabled(False)
        self.copy_summary_button.setEnabled(False)
        self.export_markdown_button.setEnabled(False)
        self.export_text_button.setEnabled(False)
        self.export_feedback_label.setText("")
        self.context_source.set_value("历史回放")
        self.context_status.set_value(loading_text)
        self.context_config.set_value("读取中")
        self.context_session.set_value(str(session_id))
        self.context_rounds.set_value("读取中")
        self.context_title.set_value("读取中")
        self.preview_markdown.setPlainText("正在读取选中的历史 session...")
        self.preview_stack.setCurrentWidget(self.preview_content)
        self.session_selected.emit(str(session_id))

    def _select_session(self, session_id: str) -> None:
        for index in range(self.session_list.count()):
            item = self.session_list.item(index)
            if item.data(Qt.UserRole) == session_id:
                self.session_list.setCurrentItem(item)
                return

    def _sync_history_selection(self) -> None:
        for session_id, widget in self._history_widgets.items():
            widget.set_selected(session_id == self._current_session_id)

    def _show_empty_preview(self) -> None:
        self._preview_session = None
        self._preview_markdown_text = ""
        self._current_session_id = None
        self.selection_block.set_value("未选择")
        self.selection_status.setText(get_status_text("waiting"))
        self.selection_status.set_tone(get_status_tone("waiting"))
        self.preview_status.setText(get_status_text("waiting"))
        self.preview_status.set_tone(get_status_tone("waiting"))
        self.preview_activity.hide()
        self.open_button.setEnabled(False)
        self.copy_id_button.setEnabled(False)
        self.copy_summary_button.setEnabled(False)
        self.export_markdown_button.setEnabled(False)
        self.export_text_button.setEnabled(False)
        self.export_feedback_label.setText("")
        self.preview_stack.setCurrentWidget(self.preview_empty)
        self._sync_history_selection()

    def show_delete_feedback(self, message: str) -> None:
        self.list_feedback_label.setText(message)

    def _copy_summary(self) -> None:
        QGuiApplication.clipboard().setText(self._preview_markdown_text if self._preview_session else "")
        if self._preview_session is not None:
            self.copy_summary_button.flash_success("已复制摘要")

    def _copy_session_id(self) -> None:
        QGuiApplication.clipboard().setText(self._current_session_id or "")
        if self._current_session_id:
            self.copy_id_button.flash_success("已复制 ID")

    def _export_session(self, export_format: str) -> None:
        if self._preview_session is None:
            return

        if export_format == "markdown":
            extension = "md"
            title = "导出 Markdown"
            file_filter = "Markdown 文件 (*.md);;所有文件 (*)"
            content = get_export_markdown_for_session(self._preview_session)
            button = self.export_markdown_button
        else:
            extension = "txt"
            title = "导出 TXT"
            file_filter = "Text 文件 (*.txt);;所有文件 (*)"
            content = get_export_text_for_session(self._preview_session)
            button = self.export_text_button

        default_name = suggest_session_export_filename(self._preview_session, extension)
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            title,
            default_name,
            file_filter,
        )
        if not file_path:
            self.export_feedback_label.setText("已取消导出，未写入文件。")
            return

        output_path = Path(file_path)
        if output_path.is_dir():
            self.export_feedback_label.setText("导出失败：请选择具体文件名，而不是文件夹。")
            return

        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            error_text = exc.strerror or exc.__class__.__name__
            self.export_feedback_label.setText(f"导出失败：{output_path.name}（{error_text}）")
            return

        label = "Markdown" if extension == "md" else "TXT"
        self.export_feedback_label.setText(f"已导出 {label}：{output_path.name}")
        button.flash_success(f"已导出 {label}")

    @staticmethod
    def _build_meta(summary: SessionSummary) -> str:
        time_text = ReplayPage._format_time(summary.completed_at or summary.created_at)
        details = [
            summary.config_name,
            get_status_text(summary.status, default="completed"),
            f"{summary.round_count} 个阶段",
            time_text,
        ]
        if summary.error:
            details.append(summary.error)
        return " · ".join(part for part in details if part)

    @staticmethod
    def _format_time(value: datetime | None) -> str:
        if value is None:
            return "未知时间"
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
