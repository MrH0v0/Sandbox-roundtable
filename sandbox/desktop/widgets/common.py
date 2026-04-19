from __future__ import annotations

import json
import re
from typing import Any

from PySide6.QtCore import QEasingCurve, QEvent, Property, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sandbox.desktop.design_tokens import TOKENS
from sandbox.desktop.theme import STATUS_TEXT, STATUS_TONE


LONG_TEXT_PATTERN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.:/\\-]{17,})")
META_SEPARATOR_PATTERN = re.compile(r"\s+(?:·|路|\|)\s+")


def soft_wrap_long_text(value: str, *, chunk_size: int = 16) -> str:
    """Insert display-only break points into long IDs, filenames and paths."""

    def wrap_match(match: re.Match[str]) -> str:
        segment = match.group(1)
        return "\u200b".join(
            segment[index : index + chunk_size]
            for index in range(0, len(segment), chunk_size)
        )

    return LONG_TEXT_PATTERN.sub(wrap_match, str(value))


def reserve_label_text_room(label: QLabel, *, extra: int = 4) -> None:
    minimum_height = label.fontMetrics().height() + extra
    label.setMinimumHeight(max(label.minimumHeight(), minimum_height))
    label.setAlignment(label.alignment() | Qt.AlignVCenter)


def refresh_style(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


class CardFrame(QFrame):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        variant: str = "card",
        padding: int | None = None,
        spacing: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SurfaceCard")
        self.setProperty("variant", variant)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            padding or TOKENS.spacing.lg,
            padding or TOKENS.spacing.lg,
            padding or TOKENS.spacing.lg,
            padding or TOKENS.spacing.lg,
        )
        self._layout.setSpacing(spacing or TOKENS.spacing.md)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(30)
        self._shadow.setOffset(0, 10)
        self._shadow.setColor(QColor(39, 52, 70, 24))
        self.setGraphicsEffect(self._shadow)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout

    def set_variant(self, variant: str) -> None:
        self.setProperty("variant", variant)
        refresh_style(self)


class SectionHeader(QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str | None = None,
        *,
        eyebrow: str | None = None,
        tone: str = "section",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        if eyebrow:
            eyebrow_label = QLabel(eyebrow)
            eyebrow_label.setObjectName("PageEyebrow")
            layout.addWidget(eyebrow_label)

        title_label = QLabel(title)
        title_label.setObjectName("PageTitle" if tone == "page" else "SectionTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle" if tone == "page" else "SectionSubtitle")
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)


class ValueBlock(QWidget):
    def __init__(self, title: str, value: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("MetricTitle")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        reserve_label_text_room(self.title_label)
        layout.addWidget(self.title_label)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.value_label.setWordWrap(True)
        self.value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        reserve_label_text_room(self.value_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
        reserve_label_text_room(self.title_label)
        reserve_label_text_room(self.value_label)
        self.updateGeometry()

    def set_wrapped_value(self, value: str) -> None:
        self.value_label.setText(soft_wrap_long_text(value))
        reserve_label_text_room(self.title_label)
        reserve_label_text_room(self.value_label)
        self.updateGeometry()


class ContextBadge(QFrame):
    def __init__(
        self,
        title: str,
        value: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ContextBadge")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("ContextBadgeLabel")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        reserve_label_text_room(self.title_label)
        layout.addWidget(self.title_label)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("ContextBadgeValue")
        self.value_label.setWordWrap(True)
        self.value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        reserve_label_text_room(self.value_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(soft_wrap_long_text(value))
        reserve_label_text_room(self.title_label)
        reserve_label_text_room(self.value_label)
        self.updateGeometry()
        self.setMinimumHeight(self.sizeHint().height())


class StatusPill(QLabel):
    def __init__(self, text: str = "", *, tone: str = "muted", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("StatusPill")
        self.setAlignment(Qt.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        refresh_style(self)


class StageChip(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StageChip")
        self.setAlignment(Qt.AlignCenter)
        self.set_state("pending")

    def set_state(self, state: str) -> None:
        self.setProperty("state", state)
        refresh_style(self)


class AppButton(QPushButton):
    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        tone: str = "secondary",
    ) -> None:
        super().__init__(text, parent)
        self._base_text = text
        self._loading_text = text
        self._loading = False
        self.setObjectName("AppButton")
        self.setProperty("tone", tone)
        self.setProperty("feedback", "")
        self.setCursor(Qt.PointingHandCursor)

        self._timer = QTimer(self)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._advance_loading_frame)
        self._loading_frame = 0
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.timeout.connect(self._restore_feedback_text)
        self._feedback_animation: QPropertyAnimation | None = None
        refresh_style(self)

    def set_loading(self, loading: bool, text: str | None = None) -> None:
        if self._loading == loading:
            return

        self._loading = loading
        self.setProperty("loading", loading)
        self.setProperty("feedback", "")
        self._feedback_timer.stop()
        self._clear_feedback_effect()
        self.setDisabled(loading)
        if text:
            self._loading_text = text
        if loading:
            self._loading_frame = 0
            self._timer.start()
            self._advance_loading_frame()
        else:
            self._timer.stop()
            self.setText(self._base_text)
        refresh_style(self)

    def set_base_text(self, text: str) -> None:
        self._base_text = text
        if not self._loading:
            self.setText(text)

    def flash_success(self, text: str, *, duration_ms: int = 1200) -> None:
        if self._loading:
            return

        self.setProperty("feedback", "success")
        self.setText(text)
        self._start_feedback_pulse()
        self._feedback_timer.start(duration_ms)
        refresh_style(self)

    def _restore_feedback_text(self) -> None:
        self.setProperty("feedback", "")
        if not self._loading:
            self.setText(self._base_text)
        refresh_style(self)

    def _start_feedback_pulse(self) -> None:
        self._clear_feedback_effect()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        effect.setOpacity(0.82)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(TOKENS.motion.fast)
        animation.setStartValue(0.82)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def cleanup() -> None:
            if self.graphicsEffect() is effect:
                self.setGraphicsEffect(None)

        animation.finished.connect(cleanup)
        animation.start()
        self._feedback_animation = animation

    def _clear_feedback_effect(self) -> None:
        if self._feedback_animation is not None:
            self._feedback_animation.stop()
            self._feedback_animation = None
        if isinstance(self.graphicsEffect(), QGraphicsOpacityEffect):
            self.setGraphicsEffect(None)

    def _advance_loading_frame(self) -> None:
        dots = "." * ((self._loading_frame % 3) + 1)
        self.setText(f"{self._loading_text}{dots}")
        self._loading_frame += 1


class AppComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AppComboBox")
        self._popup_window = QFrame(
            None,
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self._popup_window.setObjectName("ComboPopupWindow")
        self._popup_window.setAttribute(Qt.WA_TranslucentBackground, True)
        self._popup_window.setAutoFillBackground(False)

        popup_layout = QVBoxLayout(self._popup_window)
        popup_layout.setContentsMargins(0, 0, 0, 0)
        popup_layout.setSpacing(0)

        self._popup_list = QListWidget(self._popup_window)
        self._popup_list.setObjectName("ComboPopupList")
        self._popup_list.setFrameShape(QFrame.NoFrame)
        self._popup_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._popup_list.setSelectionMode(QListWidget.SingleSelection)
        self._popup_list.itemClicked.connect(self._handle_popup_item_clicked)
        popup_layout.addWidget(self._popup_list)

    def showPopup(self) -> None:
        self._sync_popup_items()
        if self._popup_list.count() == 0:
            return
        self._popup_window.resize(self.width(), self._popup_height())
        popup_pos = self.mapToGlobal(self.rect().bottomLeft())
        self._popup_window.move(popup_pos.x(), popup_pos.y() + 6)
        refresh_style(self._popup_list)
        refresh_style(self._popup_window)
        self._popup_window.show()
        self._popup_window.raise_()

    def hidePopup(self) -> None:
        self._popup_window.hide()

    def popup_window(self) -> QFrame:
        return self._popup_window

    def _sync_popup_items(self) -> None:
        self._popup_list.clear()
        for index in range(self.count()):
            item = QListWidgetItem(self.itemText(index))
            item.setData(Qt.UserRole, index)
            self._popup_list.addItem(item)
        self._popup_list.setCurrentRow(self.currentIndex())

    def _popup_height(self) -> int:
        visible_count = min(self.count(), max(self.maxVisibleItems(), 1))
        if visible_count == 0:
            return 0
        row_height = self._popup_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 36
        contents_margins = self._popup_list.contentsMargins()
        return (row_height * visible_count) + contents_margins.top() + contents_margins.bottom() + 12

    def _handle_popup_item_clicked(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.UserRole)
        if isinstance(index, int):
            self.setCurrentIndex(index)
        self.hidePopup()


class NavButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)


class ActivityBar(QProgressBar):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ActivityBar")
        self.setProperty("pulse", "")
        self.setRange(0, 0)
        self.setTextVisible(False)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(360)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._start_pulse()

    def hideEvent(self, event) -> None:
        self._stop_pulse()
        super().hideEvent(event)

    def _start_pulse(self) -> None:
        self.setProperty("pulse", "strong")
        refresh_style(self)
        self._pulse_timer.start()

    def _stop_pulse(self) -> None:
        self._pulse_timer.stop()
        self.setProperty("pulse", "")
        refresh_style(self)

    def _advance_pulse(self) -> None:
        self.setProperty("pulse", "soft" if self.property("pulse") == "strong" else "strong")
        refresh_style(self)


class MessageBanner(QFrame):
    def __init__(self, parent: QWidget | None = None, *, tone: str = "info") -> None:
        super().__init__(parent)
        self.setObjectName("MessageBanner")
        self.setProperty("tone", tone)
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QLabel("")
        self.title_label.setObjectName("BannerTitle")
        layout.addWidget(self.title_label)

        self.body_label = QLabel("")
        self.body_label.setObjectName("BannerText")
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

        self.hide()

    def set_message(self, title: str = "", body: str = "", *, tone: str = "info") -> None:
        if not title and not body:
            self.hide()
            return

        self.setProperty("tone", tone)
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.title_label.setVisible(bool(title))
        self.body_label.setVisible(bool(body))
        refresh_style(self)
        self.show()


class AnimatedStackedWidget(QStackedWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._animation: QPropertyAnimation | None = None

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if index == self.currentIndex():
            return

        super().setCurrentIndex(index)
        widget = self.currentWidget()
        if widget is None:
            return

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        effect.setOpacity(0.0)

        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(TOKENS.motion.normal)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def cleanup() -> None:
            widget.setGraphicsEffect(None)

        animation.finished.connect(cleanup)
        animation.start()
        self._animation = animation

    def setCurrentWidget(self, widget: QWidget) -> None:  # noqa: N802
        index = self.indexOf(widget)
        if index >= 0:
            self.setCurrentIndex(index)


class EmptyStateWidget(CardFrame):
    def __init__(
        self,
        title: str,
        message: str,
        parent: QWidget | None = None,
        *,
        action: QPushButton | None = None,
    ) -> None:
        super().__init__(parent, variant="secondary", padding=TOKENS.spacing.xl)
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setSpacing(TOKENS.spacing.sm)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        title_label.setAlignment(Qt.AlignCenter)
        self.body.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setObjectName("PageSubtitle")
        message_label.setWordWrap(True)
        message_label.setAlignment(Qt.AlignCenter)
        message_label.setMaximumWidth(460)
        self.body.addWidget(message_label)

        if action is not None:
            self.body.addSpacing(TOKENS.spacing.xs)
            self.body.addWidget(action, alignment=Qt.AlignCenter)


class HistoryItemWidget(QFrame):
    clicked = Signal()
    delete_requested = Signal()

    def __init__(
        self,
        *,
        title: str,
        meta: str,
        status: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryItem")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("selected", False)
        self.setProperty("hovered", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        top_row.addWidget(self.title_label, stretch=1)

        self.pill = StatusPill(
            STATUS_TEXT.get(status, status),
            tone=STATUS_TONE.get(status, "muted"),
        )
        self.pill.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        top_row.addWidget(self.pill)

        self.delete_button = AppButton("删除", tone="ghost")
        self.delete_button.setToolTip("删除这条历史记录")
        self.delete_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.delete_button.setMinimumWidth(52)
        self.delete_button.setMinimumHeight(30)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        top_row.addWidget(self.delete_button)

        layout.addLayout(top_row)

        self.meta_label = QLabel(self._format_meta(meta))
        self.meta_label.setObjectName("SubtleText")
        self.meta_label.setWordWrap(True)
        self.meta_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addWidget(self.meta_label)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        if selected:
            self.setProperty("hovered", False)
        refresh_style(self)

    def enterEvent(self, event: QEvent) -> None:
        if not self.property("selected"):
            self.setProperty("hovered", True)
            refresh_style(self)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        if self.property("hovered"):
            self.setProperty("hovered", False)
            refresh_style(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    @staticmethod
    def _format_meta(meta: str) -> str:
        parts = [
            part.strip()
            for part in META_SEPARATOR_PATTERN.split(str(meta))
            if part.strip()
        ]
        if len(parts) >= 4:
            return "\n".join(
                [
                    soft_wrap_long_text(" · ".join(parts[:3])),
                    soft_wrap_long_text(" · ".join(parts[3:])),
                ]
            )
        if len(parts) >= 2:
            return "\n".join(soft_wrap_long_text(part) for part in parts)
        return soft_wrap_long_text(meta)


class JsonTreeWidget(QTreeWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("JsonTree")
        self.setColumnCount(2)
        self.setHeaderLabels(["字段", "内容"])
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setRootIsDecorated(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._payload: Any = {}

    def set_json_data(self, payload: Any) -> None:
        self._payload = payload
        self.clear()
        root = QTreeWidgetItem(["session", self._preview_value(payload)])
        self.addTopLevelItem(root)
        self._populate(root, payload)
        self.expandToDepth(1)
        self.header().resizeSection(0, 260)
        self.header().setStretchLastSection(True)

    def _populate(self, parent: QTreeWidgetItem, value: Any) -> None:
        if isinstance(value, dict):
            for key, child_value in value.items():
                child = QTreeWidgetItem([str(key), self._preview_value(child_value)])
                parent.addChild(child)
                if isinstance(child_value, (dict, list)):
                    self._populate(child, child_value)
        elif isinstance(value, list):
            for index, child_value in enumerate(value):
                child = QTreeWidgetItem([f"[{index}]", self._preview_value(child_value)])
                parent.addChild(child)
                if isinstance(child_value, (dict, list)):
                    self._populate(child, child_value)

    @staticmethod
    def _preview_value(value: Any) -> str:
        if isinstance(value, dict):
            field_count = len(value)
            if field_count == 0:
                return "object · empty"
            suffix = "field" if field_count == 1 else "fields"
            return f"object · {field_count} {suffix}"
        if isinstance(value, list):
            item_count = len(value)
            if item_count == 0:
                return "array · empty"
            suffix = "item" if item_count == 1 else "items"
            return f"array · {item_count} {suffix}"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value).strip()
        if len(text) > 120:
            return f"{text[:117]}..."
        return text

    def to_pretty_json(self) -> str:
        return json.dumps(self._payload, ensure_ascii=False, indent=2)


def attach_list_item_widget(list_widget, item: QListWidgetItem, widget: QWidget) -> None:
    list_widget.addItem(item)
    list_widget.setItemWidget(item, widget)
    item.setSizeHint(widget.sizeHint())
