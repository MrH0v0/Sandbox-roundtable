from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from sandbox.desktop.design_tokens import THEME_PALETTES, TOKENS, Palette, alpha
from sandbox.schemas.discussion import DiscussionStage


STAGE_TITLES = {
    DiscussionStage.INDEPENDENT_JUDGMENT: "独立判断",
    DiscussionStage.CROSS_QUESTION: "交叉质询",
    DiscussionStage.REVISED_PLAN: "修正方案",
    DiscussionStage.FINAL_VERDICT: "最终裁决",
}

STATUS_TEXT = {
    "idle": "未开始",
    "waiting": "等待中",
    "loading": "加载中",
    "running": "运行中",
    "success": "已完成",
    "completed": "已完成",
    "degraded": "降级完成",
    "error": "失败",
    "failed": "失败",
    "incomplete": "未完成",
    "invalid": "已损坏",
}

STATUS_TONE = {
    "idle": "muted",
    "waiting": "muted",
    "loading": "info",
    "running": "info",
    "success": "success",
    "completed": "success",
    "degraded": "warning",
    "error": "danger",
    "failed": "danger",
    "incomplete": "warning",
    "invalid": "danger",
}

THEME_SETTINGS_KEY = "theme_key"
DEFAULT_THEME_KEY = "default"


@dataclass(frozen=True)
class ThemeOption:
    key: str
    label: str
    palette: Palette


def available_themes() -> list[ThemeOption]:
    return [
        ThemeOption(key=key, label=palette.name, palette=palette)
        for key, palette in THEME_PALETTES.items()
    ]


def get_theme(theme_key: str | None = None) -> ThemeOption:
    normalized = str(theme_key or DEFAULT_THEME_KEY).strip().lower()
    palette = THEME_PALETTES.get(normalized)
    if palette is None:
        normalized = DEFAULT_THEME_KEY
        palette = THEME_PALETTES[DEFAULT_THEME_KEY]
    return ThemeOption(key=normalized, label=palette.name, palette=palette)


def load_theme_key() -> str:
    settings = QSettings("sandbox", "roundtable-desktop")
    return get_theme(settings.value(THEME_SETTINGS_KEY, DEFAULT_THEME_KEY, str)).key


def save_theme_key(theme_key: str) -> str:
    resolved_key = get_theme(theme_key).key
    settings = QSettings("sandbox", "roundtable-desktop")
    settings.setValue(THEME_SETTINGS_KEY, resolved_key)
    settings.sync()
    return resolved_key


def build_markdown_document_css(theme_key: str | None = None) -> str:
    palette = get_theme(theme_key).palette
    return f"""
body {{
    color: {palette.text};
    font-family: "PingFang SC", "Microsoft YaHei UI", "Segoe UI";
    font-size: 14px;
    line-height: 1.78;
}}
h1 {{
    font-size: 28px;
    font-weight: 700;
    margin: 6px 0 18px 0;
    color: {palette.text_strong};
}}
h2 {{
    font-size: 20px;
    font-weight: 700;
    margin: 22px 0 12px 0;
    color: {palette.text_strong};
}}
h3 {{
    font-size: 16px;
    font-weight: 700;
    margin: 18px 0 10px 0;
    color: {palette.text};
}}
p {{
    margin: 0 0 12px 0;
}}
ul, ol {{
    margin: 0 0 16px 0;
    padding-left: 22px;
}}
li {{
    margin: 0 0 6px 0;
}}
blockquote {{
    margin: 14px 0;
    padding: 12px 16px;
    border: 1px solid {palette.border_strong};
    border-radius: 12px;
    background: {palette.surface_alt};
    color: {palette.text_muted};
}}
code, pre {{
    font-family: "Cascadia Mono", "Consolas", monospace;
}}
pre {{
    margin: 14px 0;
    padding: 14px 16px;
    background: {palette.surface_alt};
    border: 1px solid {palette.border_soft};
    border-radius: 14px;
}}
hr {{
    border: none;
    border-top: 1px solid {palette.border_soft};
    margin: 20px 0;
}}
"""


MARKDOWN_DOCUMENT_CSS = build_markdown_document_css(DEFAULT_THEME_KEY)


def normalize_status(status: str | None, *, default: str = "idle") -> str:
    if not status:
        return default

    normalized = str(status).strip().lower()
    aliases = {
        "error": "failed",
        "success": "completed",
    }
    return aliases.get(normalized, normalized)


def get_status_text(status: str | None, *, default: str = "idle") -> str:
    normalized = normalize_status(status, default=default)
    return STATUS_TEXT.get(normalized, STATUS_TEXT[default])


def get_status_tone(status: str | None, *, default: str = "muted") -> str:
    normalized = normalize_status(status, default="idle")
    return STATUS_TONE.get(normalized, default)


def build_stylesheet(theme_key: str | None = None) -> str:
    palette = get_theme(theme_key).palette
    radius = TOKENS.radius

    return f"""
QWidget {{
    background: transparent;
    color: {palette.text};
    font-size: 14px;
}}

QLabel {{
    background: transparent;
    border: none;
}}

QMainWindow,
QWidget#AppRoot {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {palette.page_bg},
        stop: 0.55 {palette.page_bg_mid},
        stop: 1 {palette.page_bg_alt}
    );
}}

QWidget#WorkspaceHost,
QWidget#PageView,
QWidget#PageCanvas,
QWidget#PageColumn,
QWidget#SideColumn,
QWidget#HeroContent,
QWidget#CardContent,
QWidget#RailSection {{
    background: transparent;
}}

QFrame#NavRail {{
    background: {alpha(palette.rail_bg, 0.94)};
    border: 1px solid {alpha(palette.border_strong, 0.95)};
    border-radius: {radius.xl}px;
}}

QFrame#SurfaceCard {{
    background: {alpha(palette.surface, 0.98)};
    border: 1px solid {alpha(palette.border_soft, 0.92)};
    border-radius: {radius.lg}px;
}}

QFrame#SurfaceCard[variant="hero"] {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {alpha(palette.surface_raised, 0.99)},
        stop: 0.52 {alpha(palette.hero_mid, 0.99)},
        stop: 1 {alpha(palette.hero_alt, 0.99)}
    );
    border: 1px solid {alpha(palette.border_strong, 0.96)};
}}

QFrame#SurfaceCard[variant="reading"] {{
    background: {alpha(palette.surface_reading, 0.995)};
    border: 1px solid {alpha(palette.border_soft, 0.96)};
}}

QFrame#SurfaceCard[variant="secondary"] {{
    background: {alpha(palette.surface_alt, 0.96)};
    border: 1px solid {alpha(palette.border_soft, 0.88)};
}}

QFrame#HistoryItem,
QFrame#MemberStateCard,
QFrame#FieldPanel,
QFrame#ContextBadge,
QFrame#MiniPanel {{
    background: {alpha(palette.surface_raised, 0.92)};
    border: 1px solid {alpha(palette.border_soft, 0.88)};
    border-radius: {radius.md}px;
}}

QFrame#HistoryItem[hovered="true"],
QFrame#MemberStateCard[hovered="true"],
QFrame#FieldPanel[hovered="true"] {{
    border: 1px solid {alpha(palette.border_hover, 0.98)};
    background: {alpha(palette.control_surface_hover, 0.98)};
}}

QFrame#HistoryItem[selected="true"] {{
    background: {alpha(palette.accent_soft, 0.96)};
    border: 1px solid {alpha(palette.accent, 0.35)};
}}

QFrame#MessageBanner {{
    border-radius: {radius.md}px;
    border: 1px solid {alpha(palette.border_soft, 0.88)};
    background: {alpha(palette.surface_alt, 0.96)};
}}

QFrame#MessageBanner[tone="danger"] {{
    background: {alpha(palette.danger_soft, 0.98)};
    border: 1px solid {alpha(palette.danger, 0.28)};
}}

QFrame#MessageBanner[tone="warning"] {{
    background: {alpha(palette.warning_soft, 0.98)};
    border: 1px solid {alpha(palette.warning, 0.28)};
}}

QFrame#MessageBanner[tone="success"] {{
    background: {alpha(palette.success_soft, 0.98)};
    border: 1px solid {alpha(palette.success, 0.28)};
}}

QFrame#MessageBanner[tone="info"] {{
    background: {alpha(palette.info_soft, 0.98)};
    border: 1px solid {alpha(palette.info, 0.28)};
}}

QLabel#BannerTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {palette.text};
}}

QLabel#BannerText {{
    font-size: 12px;
    color: {palette.text_muted};
}}

QLabel#BrandTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {palette.text_strong};
}}

QLabel#BrandSubtitle,
QLabel#RailCaption {{
    font-size: 12px;
    color: {palette.text_soft};
}}

QLabel#PageEyebrow {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: {palette.text_soft};
    text-transform: uppercase;
}}

QLabel#PageTitle {{
    font-size: 32px;
    font-weight: 700;
    color: {palette.text_strong};
}}

QLabel#PageSubtitle {{
    font-size: 13px;
    color: {palette.text_muted};
}}

QLabel#SectionTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {palette.text_strong};
}}

QLabel#SectionSubtitle,
QLabel#SubtleText,
QLabel#FieldHint {{
    font-size: 12px;
    color: {palette.text_soft};
}}

QLabel#FieldLabel,
QLabel#MetricTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {palette.text_muted};
}}

QLabel#ContextBadgeLabel {{
    font-size: 11px;
    font-weight: 700;
    color: {palette.text_soft};
}}

QLabel#ContextBadgeValue {{
    font-size: 13px;
    font-weight: 600;
    color: {palette.text};
}}

QLabel#MetricValue {{
    font-size: 15px;
    font-weight: 600;
    color: {palette.text};
}}

QLabel#StatusPill {{
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 700;
    background: {alpha(palette.neutral_soft, 0.96)};
    color: {palette.text_muted};
}}

QLabel#StatusPill[tone="muted"] {{
    background: {alpha(palette.neutral_soft, 0.96)};
    color: {palette.text_muted};
}}

QLabel#StatusPill[tone="info"] {{
    background: {alpha(palette.info_soft, 0.98)};
    color: {palette.info};
}}

QLabel#StatusPill[tone="success"] {{
    background: {alpha(palette.success_soft, 0.98)};
    color: {palette.success};
}}

QLabel#StatusPill[tone="warning"] {{
    background: {alpha(palette.warning_soft, 0.98)};
    color: {palette.warning};
}}

QLabel#StatusPill[tone="danger"] {{
    background: {alpha(palette.danger_soft, 0.98)};
    color: {palette.danger};
}}

QLabel#StageChip {{
    background: {alpha(palette.surface_alt, 0.95)};
    border: 1px solid {alpha(palette.border_soft, 0.88)};
    border-radius: {radius.md}px;
    padding: 10px 14px;
    color: {palette.text_soft};
    font-size: 13px;
    font-weight: 700;
}}

QLabel#StageChip[state="active"] {{
    background: {alpha(palette.info_soft, 0.98)};
    border: 1px solid {alpha(palette.info, 0.28)};
    color: {palette.info};
}}

QLabel#StageChip[state="done"] {{
    background: {alpha(palette.success_soft, 0.98)};
    border: 1px solid {alpha(palette.success, 0.28)};
    color: {palette.success};
}}

QPushButton#NavButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {radius.md}px;
    color: {palette.text_muted};
    font-size: 13px;
    font-weight: 700;
    padding: 12px 14px;
    text-align: left;
}}

QPushButton#NavButton:hover {{
    background: {alpha(palette.control_surface, 0.72)};
    border: 1px solid {alpha(palette.border_soft, 0.75)};
    color: {palette.text};
}}

QPushButton#NavButton:pressed {{
    background: {alpha(palette.control_surface_pressed, 0.96)};
}}

QPushButton#NavButton:checked {{
    background: {alpha(palette.control_surface, 0.96)};
    border: 1px solid {alpha(palette.border_strong, 0.96)};
    color: {palette.text_strong};
}}

QPushButton#NavButton:focus {{
    border: 1px solid {alpha(palette.focus, 0.98)};
}}

QPushButton#AppButton {{
    border-radius: {radius.md}px;
    padding: 12px 18px;
    font-size: 13px;
    font-weight: 700;
    border: 1px solid transparent;
}}

QPushButton#AppButton[tone="primary"] {{
    background: {palette.accent};
    color: {palette.control_surface};
}}

QPushButton#AppButton[tone="primary"]:hover {{
    background: {palette.accent_hover};
}}

QPushButton#AppButton[tone="primary"]:pressed {{
    background: {palette.accent_pressed};
}}

QPushButton#AppButton[tone="secondary"] {{
    background: {alpha(palette.control_surface, 0.88)};
    border: 1px solid {alpha(palette.border_strong, 0.95)};
    color: {palette.text};
}}

QPushButton#AppButton[tone="secondary"]:hover {{
    background: {alpha(palette.control_surface_hover, 0.98)};
    border: 1px solid {alpha(palette.border_hover, 0.98)};
}}

QPushButton#AppButton[tone="secondary"]:pressed {{
    background: {alpha(palette.control_surface_pressed, 0.98)};
}}

QPushButton#AppButton[tone="ghost"] {{
    background: transparent;
    color: {palette.text_muted};
    border: 1px solid transparent;
    padding: 9px 12px;
}}

QPushButton#AppButton[tone="ghost"]:hover {{
    background: {alpha(palette.control_surface, 0.72)};
    border: 1px solid {alpha(palette.border_soft, 0.72)};
    color: {palette.text};
}}

QPushButton#AppButton[tone="ghost"]:pressed {{
    background: {alpha(palette.control_surface_pressed, 0.94)};
}}

QPushButton#AppButton[tone="segment"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {palette.text_muted};
    padding: 8px 14px;
}}

QPushButton#AppButton[tone="segment"]:checked {{
    background: {alpha(palette.control_surface, 0.96)};
    border: 1px solid {alpha(palette.border_strong, 0.96)};
    color: {palette.text};
}}

QPushButton#AppButton[tone="segment"]:hover {{
    background: {alpha(palette.control_surface, 0.72)};
    border: 1px solid {alpha(palette.border_soft, 0.72)};
    color: {palette.text};
}}

QPushButton#AppButton[tone="segment"]:pressed {{
    background: {alpha(palette.control_surface_pressed, 0.94)};
}}

QPushButton#AppButton:disabled {{
    background: {alpha(palette.disabled_bg, 0.96)};
    border: 1px solid {alpha(palette.disabled_border, 0.96)};
    color: {palette.text_soft};
}}

QPushButton#AppButton[loading="true"] {{
    background: {palette.accent_hover};
}}

QPushButton#AppButton[feedback="success"] {{
    background: {palette.success};
    border: 1px solid {alpha(palette.success, 0.28)};
    color: {palette.control_surface};
}}

QPushButton#AppButton:focus {{
    border: 1px solid {alpha(palette.focus, 0.98)};
}}

QLineEdit,
QPlainTextEdit,
QComboBox {{
    background: {alpha(palette.control_surface, 0.86)};
    border: 1px solid {alpha(palette.border_soft, 0.98)};
    border-radius: {radius.md}px;
    padding: 10px 12px;
    color: {palette.text};
    selection-background-color: {alpha(palette.accent, 0.20)};
}}

QLineEdit:hover,
QPlainTextEdit:hover,
QComboBox:hover {{
    border: 1px solid {alpha(palette.border_hover, 0.98)};
    background: {alpha(palette.control_surface_hover, 0.94)};
}}

QLineEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus {{
    border: 1px solid {alpha(palette.focus, 0.98)};
    background: {alpha(palette.control_surface_hover, 0.98)};
}}

QLineEdit {{
    min-height: 22px;
}}

QPlainTextEdit {{
    padding: 12px 14px;
}}

QTextBrowser#ResultDocument,
QTextBrowser#ReplayPreview {{
    background: transparent;
    border: none;
    padding: 4px 2px;
    selection-background-color: {alpha(palette.accent, 0.18)};
}}

QTextBrowser#ResultDocument:focus,
QTextBrowser#ReplayPreview:focus {{
    border: none;
}}

QTreeWidget#JsonTree {{
    background: transparent;
    border: none;
    padding: 0;
    color: {palette.text};
}}

QTreeWidget#JsonTree::item {{
    border-radius: 10px;
    padding: 7px 6px;
}}

QTreeWidget#JsonTree::item:hover {{
    background: {alpha(palette.list_hover, 0.98)};
}}

QTreeWidget#JsonTree::item:selected {{
    background: {alpha(palette.accent_soft, 0.98)};
    color: {palette.text};
}}

QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {alpha(palette.border_soft, 0.9)};
    color: {palette.text_muted};
    font-weight: 700;
    padding: 8px 6px 10px 6px;
}}

QListWidget#SessionHistoryList,
QListWidget#EventList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
}}

QListWidget#SessionHistoryList::item,
QListWidget#EventList::item {{
    background: transparent;
    border: none;
    margin: 0 0 10px 0;
    padding: 0;
}}

QListWidget#EventList::item {{
    background: {alpha(palette.event_item_bg, 0.54)};
    border-radius: 10px;
    color: {palette.text_muted};
    padding: 8px 10px;
}}

QComboBox {{
    combobox-popup: 0;
}}

QFrame#ComboPopupWindow {{
    background: transparent;
    border: none;
}}

QComboBox::drop-down {{
    border: none;
    width: 28px;
    background: transparent;
}}

QComboBox::down-arrow {{
    width: 10px;
    height: 10px;
    margin-right: 4px;
}}

QListWidget#ComboPopupList {{
    background: {alpha(palette.surface_raised, 0.99)};
    border: 1px solid {alpha(palette.border_strong, 0.98)};
    border-radius: {radius.md}px;
    color: {palette.text};
    outline: none;
    padding: 6px;
    selection-background-color: {alpha(palette.accent_soft, 0.98)};
}}

QListWidget#ComboPopupList::item {{
    min-height: 32px;
    border-radius: 10px;
    padding: 0 10px;
    background: transparent;
}}

QListWidget#ComboPopupList::item:selected,
QListWidget#ComboPopupList::item:hover {{
    background: {alpha(palette.list_hover, 0.98)};
    color: {palette.text};
}}

QProgressBar#ActivityBar {{
    background: {alpha(palette.progress_track, 0.98)};
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
    text-align: center;
}}

QProgressBar#ActivityBar::chunk {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {palette.progress_start},
        stop: 0.55 {palette.accent},
        stop: 1 {palette.progress_end}
    );
    border-radius: 3px;
}}

QProgressBar#ActivityBar[pulse="soft"]::chunk {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {palette.progress_soft_start},
        stop: 0.55 {palette.accent_hover},
        stop: 1 {palette.progress_soft_end}
    );
}}

QToolTip {{
    background: {alpha(palette.surface_raised, 0.98)};
    color: {palette.text};
    border: 1px solid {alpha(palette.border_strong, 0.96)};
    border-radius: 8px;
    padding: 6px 8px;
}}

QScrollArea {{
    background: transparent;
    border: none;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 0;
}}

QScrollBar::handle:vertical {{
    background: {alpha(palette.scrollbar, 0.96)};
    border-radius: 5px;
    min-height: 36px;
}}

QScrollBar::handle:vertical:hover {{
    background: {alpha(palette.scrollbar_hover, 0.98)};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical,
QScrollBar:horizontal,
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: transparent;
    width: 0;
    height: 0;
}}
"""


def pick_app_font() -> QFont:
    chinese_first = [
        "PingFang SC",
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
    ]
    fallback_families = [
        "Segoe UI Variable",
        "Segoe UI",
        "SF Pro Text",
    ]

    available_families = set(QFontDatabase.families())
    chinese_writing_system = QFontDatabase.WritingSystem.SimplifiedChinese

    for family in chinese_first:
        if family not in available_families:
            continue
        if chinese_writing_system in QFontDatabase.writingSystems(family):
            return QFont(family, 10)

    for family in fallback_families:
        if family in available_families:
            return QFont(family, 10)

    return QFont("", 10)


def apply_theme(app: QApplication, theme_key: str | None = None) -> str:
    app.setStyle("Fusion")
    app.setFont(pick_app_font())
    resolved_theme = get_theme(theme_key or load_theme_key())
    palette_tokens = resolved_theme.palette

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(palette_tokens.page_bg))
    palette.setColor(QPalette.Base, QColor(palette_tokens.control_surface))
    palette.setColor(QPalette.AlternateBase, QColor(palette_tokens.surface_alt))
    palette.setColor(QPalette.Text, QColor(palette_tokens.text))
    palette.setColor(QPalette.ButtonText, QColor(palette_tokens.text))
    palette.setColor(QPalette.WindowText, QColor(palette_tokens.text))
    palette.setColor(QPalette.Highlight, QColor(palette_tokens.accent))
    palette.setColor(QPalette.HighlightedText, QColor(palette_tokens.control_surface))
    app.setPalette(palette)

    app.setStyleSheet(build_stylesheet(resolved_theme.key))
    return resolved_theme.key
