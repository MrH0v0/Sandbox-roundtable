from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.state import MemberRunState, RunStateSnapshot
from sandbox.desktop.theme import (
    STAGE_TITLES,
    get_status_text,
    get_status_tone,
    normalize_status,
)
from sandbox.desktop.widgets.common import (
    ActivityBar,
    AnimatedStackedWidget,
    AppButton,
    CardFrame,
    EmptyStateWidget,
    MessageBanner,
    SectionHeader,
    StageChip,
    StatusPill,
    ValueBlock,
)
from sandbox.schemas.discussion import (
    DiscussionProgressEvent,
    DiscussionStage,
    ProgressEventType,
)


class MemberCard(QWidget):
    def __init__(self, member_state: MemberRunState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageColumn")

        frame = CardFrame(variant="secondary", padding=TOKENS.spacing.md, spacing=TOKENS.spacing.sm)
        frame.setObjectName("MemberStateCard")
        frame.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(TOKENS.spacing.sm)

        identity_column = QVBoxLayout()
        identity_column.setContentsMargins(0, 0, 0, 0)
        identity_column.setSpacing(3)

        self.name_label = QLabel("")
        self.name_label.setObjectName("SectionTitle")
        self.name_label.setWordWrap(True)
        identity_column.addWidget(self.name_label)

        self.model_label = QLabel("")
        self.model_label.setObjectName("SubtleText")
        self.model_label.setWordWrap(True)
        identity_column.addWidget(self.model_label)
        top_row.addLayout(identity_column, stretch=1)

        self.pill = StatusPill()
        top_row.addWidget(self.pill, alignment=Qt.AlignTop)
        frame.body.addLayout(top_row)

        self.stage_label = QLabel("")
        self.stage_label.setObjectName("MetricValue")
        self.stage_label.setWordWrap(True)
        frame.body.addWidget(self.stage_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("FieldHint")
        self.detail_label.setWordWrap(True)
        frame.body.addWidget(self.detail_label)

        self.update_member_state(member_state)

    def update_member_state(self, member_state: MemberRunState) -> None:
        self.name_label.setText(member_state.name)
        self.pill.setText(get_status_text(member_state.status, default="waiting"))
        self.pill.set_tone(get_status_tone(member_state.status, default="muted"))
        self.model_label.setText(member_state.model or "未提供模型")
        stage_text = STAGE_TITLES.get(member_state.stage, "等待开始")
        self.stage_label.setText(f"阶段：{stage_text}")
        if member_state.error:
            self.detail_label.setText(f"失败摘要：{member_state.error}")
        else:
            self.detail_label.setText("当前阶段没有异常。")


class StatusPage(QWidget):
    results_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageView")
        self._member_cards: dict[str, MemberCard] = {}
        self._event_items: dict[tuple[str, ...], QListWidgetItem] = {}

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = AnimatedStackedWidget()
        root_layout.addWidget(self.stack)

        self.empty_state = EmptyStateWidget(
            "还没有运行中的讨论",
            "从“新建沙盘”页发起任务后，这里会持续显示当前运行的阶段进度、成员状态和关键事件。",
        )
        self.stack.addWidget(self.empty_state)

        self.content = QWidget()
        self.content.setObjectName("PageCanvas")
        self.stack.addWidget(self.content)
        self._build_content()
        self.stack.setCurrentWidget(self.empty_state)

    def set_run_state(self, run_state: RunStateSnapshot | None) -> None:
        if run_state is None:
            self.stack.setCurrentWidget(self.empty_state)
            return

        self.stack.setCurrentWidget(self.content)
        self.scenario_block.set_value(run_state.scenario_title or "未命名场景")
        self.config_block.set_wrapped_value(run_state.config_name or "未指定")
        self.session_block.set_wrapped_value(run_state.session_id or "准备中")
        self.message_block.set_wrapped_value(run_state.last_message or "等待任务开始。")

        status_key = self._resolve_run_status(run_state)
        self.status_pill.setText(get_status_text(status_key))
        self.status_pill.set_tone(get_status_tone(status_key))

        self.current_stage_label.setText(STAGE_TITLES.get(run_state.current_stage, "等待开始"))
        self.activity_bar.setVisible(status_key in {"loading", "running"})
        self._update_token_usage(run_state)

        for stage, chip in self.stage_chips.items():
            if stage in run_state.completed_stages:
                chip.set_state("done")
            elif run_state.current_stage == stage and run_state.is_running:
                chip.set_state("active")
            elif run_state.current_stage == stage and not run_state.is_running:
                chip.set_state("done")
            else:
                chip.set_state("pending")

        self._update_banner(run_state, status_key)
        self._render_members(run_state.member_states)
        self._render_events(run_state.events)
        self.open_results_button.setEnabled(not run_state.is_running and bool(run_state.session_id))

    def _build_content(self) -> None:
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(0, 0, 0, TOKENS.spacing.xxl)
        layout.setSpacing(TOKENS.spacing.lg)

        hero = CardFrame(variant="hero", padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.md)
        hero.body.addWidget(
            SectionHeader(
                "运行中状态",
                "这里专门跟踪当前运行的 session。阶段进度、成员状态和关键事件都会实时更新，不与历史回放共用同一份展示来源。",
                eyebrow="Live Status",
                tone="page",
            )
        )

        header_row = QHBoxLayout()
        header_row.setSpacing(TOKENS.spacing.md)

        meta_column = QVBoxLayout()
        meta_column.setSpacing(TOKENS.spacing.md)
        metrics = QGridLayout()
        metrics.setHorizontalSpacing(TOKENS.spacing.md)
        metrics.setVerticalSpacing(TOKENS.spacing.sm)
        self.scenario_block = ValueBlock("场景")
        self.config_block = ValueBlock("配置")
        self.session_block = ValueBlock("Session ID")
        self.message_block = ValueBlock("最近事件")
        metrics.addWidget(self.scenario_block, 0, 0)
        metrics.addWidget(self.config_block, 0, 1)
        metrics.addWidget(self.session_block, 1, 0)
        metrics.addWidget(self.message_block, 1, 1)
        meta_column.addLayout(metrics)

        self.current_stage_label = QLabel("等待开始")
        self.current_stage_label.setObjectName("SectionTitle")
        meta_column.addWidget(self.current_stage_label)

        self.banner = MessageBanner(tone="info")
        meta_column.addWidget(self.banner)
        header_row.addLayout(meta_column, stretch=1)

        self.status_summary_panel = QFrame()
        self.status_summary_panel.setObjectName("MiniPanel")
        self.status_summary_panel.setMinimumWidth(340)
        self.status_summary_panel.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        side_column = QVBoxLayout(self.status_summary_panel)
        side_column.setContentsMargins(
            TOKENS.spacing.md,
            TOKENS.spacing.md,
            TOKENS.spacing.md,
            TOKENS.spacing.md,
        )
        side_column.setSpacing(TOKENS.spacing.sm)
        status_title = QLabel("整体状态")
        status_title.setObjectName("MetricTitle")
        side_column.addWidget(status_title)
        self.status_pill = StatusPill("未开始")
        side_column.addWidget(self.status_pill, alignment=Qt.AlignLeft)
        self.activity_bar = ActivityBar()
        side_column.addWidget(self.activity_bar)
        token_title = QLabel("Token 消耗")
        token_title.setObjectName("MetricTitle")
        side_column.addWidget(token_title)
        self.token_total_block = ValueBlock("总 Token")
        self.token_io_block = ValueBlock("输入 / 输出")
        self.token_call_block = ValueBlock("模型调用")
        side_column.addWidget(self.token_total_block)
        side_column.addWidget(self.token_io_block)
        side_column.addWidget(self.token_call_block)
        self.open_results_button = AppButton("查看当前运行结果", tone="secondary")
        self.open_results_button.clicked.connect(self.results_requested.emit)
        self.open_results_button.setEnabled(False)
        side_column.addWidget(self.open_results_button)
        side_column.addStretch(1)
        header_row.addWidget(self.status_summary_panel, stretch=0)
        hero.body.addLayout(header_row)

        stage_row = QHBoxLayout()
        stage_row.setSpacing(TOKENS.spacing.sm)
        self.stage_chips: dict[DiscussionStage, StageChip] = {}
        for stage in (
            DiscussionStage.INDEPENDENT_JUDGMENT,
            DiscussionStage.CROSS_QUESTION,
            DiscussionStage.REVISED_PLAN,
            DiscussionStage.FINAL_VERDICT,
        ):
            chip = StageChip(STAGE_TITLES[stage])
            self.stage_chips[stage] = chip
            stage_row.addWidget(chip)
        hero.body.addLayout(stage_row)
        layout.addWidget(hero)

        body_row = QHBoxLayout()
        body_row.setSpacing(TOKENS.spacing.lg)
        layout.addLayout(body_row, stretch=1)

        self.member_card = CardFrame(padding=TOKENS.spacing.xl, spacing=TOKENS.spacing.lg)
        self.member_card.setMinimumHeight(360)
        self.member_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.member_card.body.addWidget(
            SectionHeader(
                "成员状态",
                "成员失败会单独标记，其余成员的结果仍然继续展示。",
            )
        )
        self.member_grid = QGridLayout()
        self.member_grid.setHorizontalSpacing(TOKENS.spacing.md)
        self.member_grid.setVerticalSpacing(TOKENS.spacing.md)
        self.member_card.body.addLayout(self.member_grid)
        body_row.addWidget(self.member_card, stretch=5)

        self.event_card = CardFrame(variant="secondary", padding=TOKENS.spacing.lg, spacing=TOKENS.spacing.md)
        self.event_card.setMinimumWidth(320)
        self.event_card.setMinimumHeight(360)
        self.event_card.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Expanding)
        self.event_card.body.addWidget(
            SectionHeader(
                "进度事件",
                "保留最近一段时间的事件流，方便判断当前运行停在哪个阶段。",
            )
        )
        self.events_list = QListWidget()
        self.events_list.setObjectName("EventList")
        self.events_list.setMinimumWidth(280)
        self.events_list.setWordWrap(True)
        self.event_card.body.addWidget(self.events_list, stretch=1)
        body_row.addWidget(self.event_card, stretch=3)

    def _update_banner(self, run_state: RunStateSnapshot, status_key: str) -> None:
        if status_key == "failed":
            self.banner.set_message(
                "当前运行失败",
                run_state.error or "本轮讨论未能完成。请结合最近事件和错误信息判断失败点。",
                tone="danger",
            )
            return

        if status_key == "degraded":
            self.banner.set_message(
                "当前运行已降级完成",
                "主流程已经结束，但至少有一个环节发生异常并触发了回退或局部失败。查看结果时请优先确认哪些结论仍可用。",
                tone="warning",
            )
            return

        if status_key == "loading":
            self.banner.set_message(
                "当前运行正在加载",
                "讨论请求已提交，正在初始化 session 和执行上下文。",
                tone="info",
            )
            return

        if status_key == "running":
            self.banner.set_message(
                "当前运行正在进行",
                "这里展示的是当前这一轮讨论的实时上下文。切到历史回放不会覆盖这里对应的结果来源。",
                tone="info",
            )
            return

        self.banner.set_message(
            "当前运行已完成",
            "可以打开“当前运行结果”，也可以单独去历史回放查看过去的 session。两者现在是分开的。",
            tone="success",
        )

    def _update_token_usage(self, run_state: RunStateSnapshot) -> None:
        usage = run_state.token_usage
        suffix = "（估算）" if usage.estimated else ""
        self.token_total_block.set_value(f"{usage.total_tokens:,}{suffix}")
        self.token_io_block.set_value(
            f"输入 {usage.input_tokens:,} / 输出 {usage.output_tokens:,}"
        )
        self.token_call_block.set_value(f"{usage.call_count:,} 次调用")

    def _resolve_run_status(self, run_state: RunStateSnapshot) -> str:
        if run_state.error:
            return "failed"

        if run_state.is_running:
            if not run_state.session_id:
                return "loading"
            return "running"

        final_event = self._find_last_terminal_event(run_state.events)
        if final_event is not None:
            if final_event.event_type == ProgressEventType.SESSION_FAILED:
                return "failed"
            return normalize_status(final_event.status, default="completed")

        if run_state.completed_at is not None:
            return "completed"

        return "waiting"

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

    def _render_members(self, member_states: dict[str, MemberRunState]) -> None:
        active_member_ids = set(member_states)
        for member_id in list(self._member_cards):
            if member_id in active_member_ids:
                continue
            card = self._member_cards.pop(member_id)
            self.member_grid.removeWidget(card)
            card.deleteLater()

        for index, (member_id, member_state) in enumerate(member_states.items()):
            card = self._member_cards.get(member_id)
            if card is None:
                card = MemberCard(member_state)
                self._member_cards[member_id] = card
            else:
                card.update_member_state(member_state)
            row = index // 2
            column = index % 2
            self.member_grid.addWidget(card, row, column)

    def _render_events(self, events: list[DiscussionProgressEvent]) -> None:
        visible_events = list(reversed(events[-50:]))
        visible_keys = [self._event_key(event) for event in visible_events]

        for event_key in list(self._event_items):
            if event_key in visible_keys:
                continue
            item = self._event_items.pop(event_key)
            row = self.events_list.row(item)
            if row >= 0:
                self.events_list.takeItem(row)

        for index, event in enumerate(visible_events):
            event_key = self._event_key(event)
            item = self._event_items.get(event_key)
            if item is None:
                item = QListWidgetItem()
                self._event_items[event_key] = item
                self.events_list.insertItem(index, item)
            else:
                current_row = self.events_list.row(item)
                if current_row >= 0 and current_row != index:
                    self.events_list.takeItem(current_row)
                    self.events_list.insertItem(index, item)
            item.setText(self._format_event_text(event))

    def _event_key(self, event: DiscussionProgressEvent) -> tuple[str, ...]:
        return (
            event.event_type.value,
            event.session_id,
            event.created_at.isoformat(),
            event.stage.value if event.stage is not None else "",
            event.member_id or "",
            event.status or "",
            event.error or "",
            event.message or "",
        )

    def _format_event_text(self, event: DiscussionProgressEvent) -> str:
        timestamp = self._format_time(event.created_at)
        actor = event.member_name or STAGE_TITLES.get(event.stage, "系统")
        message = event.message or "状态已更新。"
        return f"{timestamp}  {actor}\n{message}"

    @staticmethod
    def _format_time(value: datetime | None) -> str:
        if value is None:
            return "--:--:--"
        return value.astimezone().strftime("%H:%M:%S")
