from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.state import RESULT_SOURCE_CURRENT_RUN, RESULT_SOURCE_HISTORY_REPLAY
from sandbox.desktop.theme import (
    build_markdown_document_css,
    get_status_text,
    get_status_tone,
    normalize_status,
)
from sandbox.desktop.widgets.common import (
    AnimatedStackedWidget,
    AppButton,
    CardFrame,
    ContextBadge,
    EmptyStateWidget,
    JsonTreeWidget,
    SectionHeader,
    StatusPill,
    ValueBlock,
)
from sandbox.renderers.markdown import session_markdown_for_display
from sandbox.renderers.session_export import (
    get_export_markdown_for_session,
    get_export_text_for_session,
    suggest_session_export_filename,
)
from sandbox.schemas.discussion import SessionRecord


class ResultsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self._current_session: SessionRecord | None = None
        self._current_markdown_text = ""
        self._session_source = RESULT_SOURCE_CURRENT_RUN

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = AnimatedStackedWidget()
        root_layout.addWidget(self.stack)

        self.empty_state = EmptyStateWidget(
            "还没有可查看的结果",
            "讨论完成后，这里会优先显示适合阅读的 Markdown 摘要。JSON 会保留在次级视图里，用于回查结构化细节。",
        )
        self.stack.addWidget(self.empty_state)

        self.content_scroll = QScrollArea()
        self.content_scroll.setObjectName("PageScrollArea")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.content = QWidget()
        self.content.setObjectName("PageCanvas")
        self.content_scroll.setWidget(self.content)
        self.stack.addWidget(self.content_scroll)
        self._build_content()
        self.stack.setCurrentWidget(self.empty_state)
        self.copy_markdown_button.setEnabled(False)
        self.copy_json_button.setEnabled(False)
        self.export_markdown_button.setEnabled(False)
        self.export_text_button.setEnabled(False)
        self.markdown_button.setEnabled(False)
        self.json_button.setEnabled(False)

    def set_session(self, session: SessionRecord | None, source: str = RESULT_SOURCE_CURRENT_RUN) -> None:
        self._current_session = session
        self._session_source = source

        if session is None:
            self._current_markdown_text = ""
            self.stack.setCurrentWidget(self.empty_state)
            self.copy_markdown_button.setEnabled(False)
            self.copy_json_button.setEnabled(False)
            self.export_markdown_button.setEnabled(False)
            self.export_text_button.setEnabled(False)
            self.markdown_button.setEnabled(False)
            self.json_button.setEnabled(False)
            return

        self.stack.setCurrentWidget(self.content_scroll)
        self.copy_markdown_button.setEnabled(True)
        self.copy_json_button.setEnabled(True)
        self.export_markdown_button.setEnabled(True)
        self.export_text_button.setEnabled(True)
        self.markdown_button.setEnabled(True)
        self.json_button.setEnabled(True)

        session_status = normalize_status(getattr(session.status, "value", session.status), default="completed")
        status_text = get_status_text(session_status, default="completed")
        status_tone = get_status_tone(session_status, default="muted")
        source_text = self._format_source(source)

        self._set_top_summary_value(self.title_value_label, session.scenario.title, max_chars=36)
        self._set_top_summary_value(self.config_value_label, session.config_name, max_chars=32)
        self._set_top_summary_value(
            self.session_value_label,
            session.session_id,
            max_chars=22,
            middle=True,
        )
        self._set_top_summary_value(self.round_value_label, str(len(session.rounds)), max_chars=8)
        self._set_top_summary_value(
            self.time_value_label,
            self._format_time(session.completed_at or session.created_at),
            max_chars=20,
        )
        self._update_token_usage(session)

        self.source_status.setText(source_text)
        self.source_status.set_tone(self._source_tone(source))
        self.result_status.setText(status_text)
        self.result_status.set_tone(status_tone)

        self.context_source.set_value(source_text)
        self.context_status.set_value(status_text)
        self.context_config.set_value(session.config_name)
        self.context_session.set_value(session.session_id)
        self.context_rounds.set_value(f"{len(session.rounds)} 个阶段")
        self.context_title.set_value(session.scenario.title)

        markdown_text = session_markdown_for_display(session).strip() or "# 空结果\n当前 session 暂无 Markdown 内容。"
        self._current_markdown_text = markdown_text
        self.markdown_view.setMarkdown(markdown_text)
        self._fit_markdown_view_to_content()
        QTimer.singleShot(0, self._fit_markdown_view_to_content)
        self.json_view.set_json_data(session.model_dump(mode="json"))
        self.reading_hint.setText(self._build_reading_hint(session_status))
        self._set_view("markdown")

    def _build_content(self) -> None:
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, TOKENS.spacing.xxl)
        layout.setSpacing(TOKENS.spacing.lg)

        hero = CardFrame(variant="hero", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        hero.body.addWidget(
            SectionHeader(
                "结果查看",
                "这里优先服务于阅读、复盘和复制关键内容，而不是把 session 原始输出直接摊开。",
                eyebrow="Reading Room",
                tone="page",
            )
        )

        top_row = QHBoxLayout()
        top_row.setSpacing(TOKENS.spacing.md)
        top_row.setAlignment(Qt.AlignTop)

        self.result_metrics_panel = QFrame()
        self.result_metrics_panel.setObjectName("MiniPanel")
        self.result_metrics_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.result_metrics_panel.setMaximumHeight(112)
        metrics_grid = QGridLayout(self.result_metrics_panel)
        metrics_grid.setContentsMargins(
            TOKENS.spacing.lg,
            TOKENS.spacing.md,
            TOKENS.spacing.lg,
            TOKENS.spacing.md,
        )
        metrics_grid.setHorizontalSpacing(TOKENS.spacing.lg)
        metrics_grid.setVerticalSpacing(4)

        self.title_value_label = self._make_summary_value_label()
        self.config_value_label = self._make_summary_value_label()
        self.session_value_label = self._make_summary_value_label()
        self.round_value_label = self._make_summary_value_label(maximum_width=96)
        self.time_value_label = self._make_summary_value_label()
        summary_fields = [
            ("场景", self.title_value_label, 3),
            ("配置", self.config_value_label, 2),
            ("Session ID", self.session_value_label, 2),
            ("阶段数", self.round_value_label, 0),
            ("完成时间", self.time_value_label, 1),
        ]
        for column, (title, value_label, stretch) in enumerate(summary_fields):
            metrics_grid.addWidget(self._make_summary_title_label(title), 0, column)
            metrics_grid.addWidget(value_label, 1, column)
            metrics_grid.setColumnStretch(column, stretch)
        top_row.addWidget(self.result_metrics_panel, 1, Qt.AlignTop)

        self.result_summary_panel = QFrame()
        self.result_summary_panel.setObjectName("MiniPanel")
        self.result_summary_panel.setMinimumWidth(280)
        self.result_summary_panel.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Maximum)
        side_column = QVBoxLayout(self.result_summary_panel)
        side_column.setContentsMargins(
            TOKENS.spacing.md,
            TOKENS.spacing.md,
            TOKENS.spacing.md,
            TOKENS.spacing.md,
        )
        side_column.setSpacing(TOKENS.spacing.sm)

        source_title = QLabel("结果来源")
        source_title.setObjectName("MetricTitle")
        side_column.addWidget(source_title)
        self.source_status = StatusPill("等待结果", tone="muted")
        side_column.addWidget(self.source_status, alignment=Qt.AlignLeft)

        status_title = QLabel("完成状态")
        status_title.setObjectName("MetricTitle")
        side_column.addWidget(status_title)
        self.result_status = StatusPill("等待结果", tone="muted")
        side_column.addWidget(self.result_status, alignment=Qt.AlignLeft)

        token_title = QLabel("Token 消耗")
        token_title.setObjectName("MetricTitle")
        side_column.addWidget(token_title)
        self.token_total_block = ValueBlock("总 Token")
        self.token_io_block = ValueBlock("输入 / 输出")
        self.token_call_block = ValueBlock("模型调用")
        side_column.addWidget(self.token_total_block)
        side_column.addWidget(self.token_io_block)
        side_column.addWidget(self.token_call_block)
        top_row.addWidget(self.result_summary_panel, 0, Qt.AlignTop)

        hero.body.addLayout(top_row)
        layout.addWidget(hero)

        context_card = CardFrame(variant="secondary", padding=TOKENS.spacing.lg, spacing=TOKENS.spacing.md)
        context_card.body.addWidget(
            SectionHeader(
                "先读后查",
                "先确认这份结果从哪来、对应哪套配置、当前是否可靠，再决定要继续阅读摘要还是核对结构化 JSON。",
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
        context_card.body.addLayout(context_grid)
        layout.addWidget(context_card)

        toolbar_card = CardFrame(variant="secondary", padding=TOKENS.spacing.lg, spacing=TOKENS.spacing.sm)
        toolbar_card.body.addWidget(
            SectionHeader(
                "阅读与复制",
                "Markdown 是主视图，用于快速阅读结论。JSON 保留给核查字段。复制动作拆开后，路径更清楚。",
            )
        )

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(TOKENS.spacing.sm)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self.markdown_button = AppButton("阅读摘要", tone="segment")
        self.markdown_button.setCheckable(True)
        self.markdown_button.setChecked(True)
        self.markdown_button.clicked.connect(lambda: self._set_view("markdown"))
        self.button_group.addButton(self.markdown_button)
        toggle_row.addWidget(self.markdown_button)

        self.json_button = AppButton("查看 JSON", tone="segment")
        self.json_button.setCheckable(True)
        self.json_button.clicked.connect(lambda: self._set_view("json"))
        self.button_group.addButton(self.json_button)
        toggle_row.addWidget(self.json_button)

        toggle_row.addStretch(1)
        self.copy_markdown_button = AppButton("复制 Markdown 摘要", tone="secondary")
        self.copy_markdown_button.clicked.connect(self._copy_markdown_summary)
        toggle_row.addWidget(self.copy_markdown_button)

        self.copy_json_button = AppButton("复制 Session JSON", tone="ghost")
        self.copy_json_button.clicked.connect(self._copy_json_payload)
        toggle_row.addWidget(self.copy_json_button)

        self.export_markdown_button = AppButton("导出 Markdown", tone="secondary")
        self.export_markdown_button.clicked.connect(lambda: self._export_session("markdown"))
        toggle_row.addWidget(self.export_markdown_button)

        self.export_text_button = AppButton("导出 TXT", tone="ghost")
        self.export_text_button.clicked.connect(lambda: self._export_session("text"))
        toggle_row.addWidget(self.export_text_button)
        toolbar_card.body.addLayout(toggle_row)

        self.reading_hint = QLabel("默认打开 Markdown 摘要。只有在核对结构和字段时再切换到 JSON。")
        self.reading_hint.setObjectName("SubtleText")
        self.reading_hint.setWordWrap(True)
        toolbar_card.body.addWidget(self.reading_hint)
        layout.addWidget(toolbar_card)

        self.reading_card = CardFrame(variant="reading", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        self.reading_card.setMinimumHeight(420)
        self.reading_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.view_stack = AnimatedStackedWidget()
        self.view_stack.setMinimumHeight(360)
        self.view_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.markdown_view = QTextBrowser()
        self.markdown_view.setObjectName("ResultDocument")
        self.markdown_view.setMinimumHeight(360)
        self.markdown_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.markdown_view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.markdown_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.markdown_view.setOpenExternalLinks(False)
        self.markdown_view.document().setDefaultStyleSheet(build_markdown_document_css())
        self.markdown_view.document().setDocumentMargin(TOKENS.spacing.md)
        self.view_stack.addWidget(self.markdown_view)

        self.json_view = JsonTreeWidget()
        self.json_view.setMinimumHeight(360)
        self.view_stack.addWidget(self.json_view)

        self.reading_card.body.addWidget(self.view_stack)
        layout.addWidget(self.reading_card)

    def refresh_theme(self, theme_key: str | None = None) -> None:
        self.markdown_view.document().setDefaultStyleSheet(build_markdown_document_css(theme_key))
        if self._current_markdown_text:
            self.markdown_view.setMarkdown(self._current_markdown_text)
        self._fit_markdown_view_to_content()

    def _make_summary_title_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("MetricTitle")
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        return label

    def _make_summary_value_label(self, *, maximum_width: int | None = None) -> QLabel:
        label = QLabel("")
        label.setObjectName("MetricValue")
        label.setWordWrap(False)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        if maximum_width is not None:
            label.setMaximumWidth(maximum_width)
        return label

    def _set_top_summary_value(
        self,
        label: QLabel,
        value: str,
        *,
        max_chars: int,
        middle: bool = False,
    ) -> None:
        full_text = str(value).strip() or "-"
        display_text = (
            self._middle_elide_text(full_text, max_chars)
            if middle
            else self._right_elide_text(full_text, max_chars)
        )
        label.setText(display_text)
        label.setToolTip(full_text if display_text != full_text else "")

    @staticmethod
    def _right_elide_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return f"{text[: max_chars - 3]}..."

    @staticmethod
    def _middle_elide_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars <= 7:
            return ResultsPage._right_elide_text(text, max_chars)
        head = max(4, (max_chars - 3) // 2)
        tail = max_chars - 3 - head
        return f"{text[:head]}...{text[-tail:]}"

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_markdown_view_to_content)

    def _fit_markdown_view_to_content(self) -> None:
        if not hasattr(self, "markdown_view"):
            return

        width = max(1, self.markdown_view.viewport().width())
        document = self.markdown_view.document()
        document.setTextWidth(width)

    def _update_token_usage(self, session: SessionRecord) -> None:
        usage = session.token_usage
        suffix = "（估算）" if usage.estimated else ""
        self.token_total_block.set_value(f"{usage.total_tokens:,}{suffix}")
        self.token_io_block.set_value(
            f"输入 {usage.input_tokens:,} / 输出 {usage.output_tokens:,}"
        )
        self.token_call_block.set_value(f"{usage.call_count:,} 次调用")

    def _set_view(self, view_name: str) -> None:
        if view_name == "json":
            self.view_stack.setCurrentWidget(self.json_view)
            self.json_button.setChecked(True)
            self.reading_hint.setText("当前处于 JSON 核查视图。阅读主内容时建议回到 Markdown 摘要。")
            return

        self.view_stack.setCurrentWidget(self.markdown_view)
        self.markdown_button.setChecked(True)
        if self._current_session is None:
            self.reading_hint.setText("默认打开 Markdown 摘要。只有在核对结构和字段时再切换到 JSON。")
            return

        session_status = normalize_status(
            getattr(self._current_session.status, "value", self._current_session.status),
            default="completed",
        )
        self.reading_hint.setText(self._build_reading_hint(session_status))

    def _copy_markdown_summary(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self._current_markdown_text if self._current_session else "")
        if self._current_session is not None:
            self.copy_markdown_button.flash_success("已复制 Markdown")

    def _copy_json_payload(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.json_view.to_pretty_json() if self._current_session else "")
        if self._current_session is not None:
            self.copy_json_button.flash_success("已复制 JSON")

    def _export_session(self, export_format: str) -> None:
        if self._current_session is None:
            return

        if export_format == "markdown":
            extension = "md"
            title = "导出 Markdown"
            file_filter = "Markdown 文件 (*.md);;所有文件 (*)"
            content = get_export_markdown_for_session(self._current_session)
            button = self.export_markdown_button
        else:
            extension = "txt"
            title = "导出 TXT"
            file_filter = "Text 文件 (*.txt);;所有文件 (*)"
            content = get_export_text_for_session(self._current_session)
            button = self.export_text_button

        default_name = suggest_session_export_filename(self._current_session, extension)
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            title,
            default_name,
            file_filter,
        )
        if not file_path:
            self.reading_hint.setText("已取消导出，未写入文件。")
            return

        output_path = Path(file_path)
        if output_path.is_dir():
            self.reading_hint.setText("导出失败：请选择具体文件名，而不是文件夹。")
            return

        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            error_text = exc.strerror or exc.__class__.__name__
            self.reading_hint.setText(f"导出失败：{output_path.name}（{error_text}）")
            return

        label = "Markdown" if extension == "md" else "TXT"
        self.reading_hint.setText(f"已导出 {label}：{output_path.name}")
        button.flash_success(f"已导出 {label}")

    @staticmethod
    def _format_source(source: str) -> str:
        if source == RESULT_SOURCE_HISTORY_REPLAY:
            return "历史回放"
        return "当前运行结果"

    @staticmethod
    def _source_tone(source: str) -> str:
        if source == RESULT_SOURCE_HISTORY_REPLAY:
            return "warning"
        return "info"

    @staticmethod
    def _build_reading_hint(status: str) -> str:
        if status == "degraded":
            return "当前是降级完成结果。先阅读 Markdown 摘要确认哪些结论仍可用，再按需查看 JSON 核对失败点。"
        if status == "failed":
            return "当前是失败结果。先阅读 Markdown 摘要了解失败位置，再按需查看 JSON 排查细节。"
        if status in {"loading", "running"}:
            return "当前结果仍在处理中。优先查看摘要里的最新内容，结构化 JSON 可能还不完整。"
        return "当前处于 Markdown 摘要视图。这里适合先读结论、分歧和推荐行动。"

    @staticmethod
    def _format_time(value: datetime | None) -> str:
        if value is None:
            return "未完成"
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
