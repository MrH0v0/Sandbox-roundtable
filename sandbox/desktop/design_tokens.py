from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpacingScale:
    xs: int = 8
    sm: int = 12
    md: int = 16
    lg: int = 24
    xl: int = 32
    xxl: int = 40


@dataclass(frozen=True)
class RadiusScale:
    sm: int = 12
    md: int = 18
    lg: int = 24
    xl: int = 30


@dataclass(frozen=True)
class MotionScale:
    fast: int = 120
    normal: int = 180
    slow: int = 220


@dataclass(frozen=True)
class Palette:
    name: str = "默认"
    page_bg: str = "#F5F2EC"
    page_bg_mid: str = "#F6F3EE"
    page_bg_alt: str = "#EEF2F7"
    rail_bg: str = "#F7F4EE"
    surface: str = "#FCFAF6"
    surface_alt: str = "#F4EFE7"
    surface_raised: str = "#FFFDFC"
    surface_reading: str = "#FFFDF8"
    hero_mid: str = "#F8F4EE"
    hero_alt: str = "#F1F4FB"
    border_soft: str = "#E6DED3"
    border_strong: str = "#D8D0C5"
    border_hover: str = "#D7CFC3"
    text: str = "#1B2430"
    text_strong: str = "#101828"
    text_muted: str = "#667085"
    text_soft: str = "#7A8391"
    accent: str = "#C8895D"
    accent_hover: str = "#B87549"
    accent_pressed: str = "#9C5F36"
    accent_soft: str = "#F4E5D4"
    neutral_soft: str = "#EEF1F5"
    control_surface: str = "#FFFFFF"
    control_surface_hover: str = "#FFFFFF"
    control_surface_pressed: str = "#F4F0E9"
    success: str = "#1F7A4C"
    success_soft: str = "#E8F6EE"
    warning: str = "#B7791F"
    warning_soft: str = "#FFF4DE"
    danger: str = "#C85A46"
    danger_soft: str = "#FFF0EC"
    info: str = "#C8895D"
    info_soft: str = "#F4E5D4"
    disabled_bg: str = "#EEF1F5"
    disabled_border: str = "#CAD1DC"
    list_hover: str = "#F5F7FB"
    event_item_bg: str = "#FFFFFF"
    progress_track: str = "#E6EBF4"
    progress_start: str = "#E4C0A1"
    progress_end: str = "#DCA77B"
    progress_soft_start: str = "#F0D1B6"
    progress_soft_end: str = "#E4B88F"
    scrollbar: str = "#C8CEC9"
    scrollbar_hover: str = "#AEB6C1"
    shadow: str = "#273446"
    focus: str = "#D7A074"


@dataclass(frozen=True)
class DesignTokens:
    spacing: SpacingScale = SpacingScale()
    radius: RadiusScale = RadiusScale()
    motion: MotionScale = MotionScale()
    palette: Palette = Palette()


TOKENS = DesignTokens()


THEME_PALETTES: dict[str, Palette] = {
    "default": Palette(),
    "rem": Palette(
        name="雷姆",
        page_bg="#EEF6FB",
        page_bg_mid="#F4F8FC",
        page_bg_alt="#F2F0FA",
        rail_bg="#F1F7FC",
        surface="#FAFDFF",
        surface_alt="#EEF6FB",
        surface_raised="#FFFFFF",
        surface_reading="#FBFEFF",
        hero_mid="#F2F8FE",
        hero_alt="#F2F0FA",
        border_soft="#D9E8F3",
        border_strong="#C7D8E8",
        border_hover="#B7CFE5",
        text="#1B2838",
        text_strong="#102033",
        text_muted="#5C7188",
        text_soft="#78899B",
        accent="#5B93C8",
        accent_hover="#477FAF",
        accent_pressed="#35678F",
        accent_soft="#E4F1FB",
        neutral_soft="#EAF2F8",
        control_surface="#FFFFFF",
        control_surface_hover="#F8FCFF",
        control_surface_pressed="#EAF4FB",
        success="#237A63",
        success_soft="#E6F5F0",
        warning="#9A6A16",
        warning_soft="#FFF5DA",
        danger="#B95766",
        danger_soft="#FFF0F3",
        info="#5B93C8",
        info_soft="#E4F1FB",
        disabled_bg="#E8EEF5",
        disabled_border="#C9D5E2",
        list_hover="#EEF7FD",
        event_item_bg="#FFFFFF",
        progress_track="#DCEAF5",
        progress_start="#A9D7F0",
        progress_end="#8A83C8",
        progress_soft_start="#D4ECFA",
        progress_soft_end="#BDB7E8",
        scrollbar="#B8CADB",
        scrollbar_hover="#91AAC1",
        shadow="#20364F",
        focus="#7BAFDA",
    ),
    "monochrome": Palette(
        name="黑白",
        page_bg="#F3F3F1",
        page_bg_mid="#F8F8F6",
        page_bg_alt="#E9E9E6",
        rail_bg="#F0F0EE",
        surface="#FBFBFA",
        surface_alt="#EFEFED",
        surface_raised="#FFFFFF",
        surface_reading="#FEFEFD",
        hero_mid="#F6F6F4",
        hero_alt="#EDEDEB",
        border_soft="#DADAD6",
        border_strong="#C5C5BF",
        border_hover="#AFAFAA",
        text="#171717",
        text_strong="#0D0D0D",
        text_muted="#555555",
        text_soft="#777777",
        accent="#242424",
        accent_hover="#3A3A3A",
        accent_pressed="#0F0F0F",
        accent_soft="#E8E8E5",
        neutral_soft="#ECECE9",
        control_surface="#FFFFFF",
        control_surface_hover="#FAFAF8",
        control_surface_pressed="#E9E9E6",
        success="#2D5D4B",
        success_soft="#E8EFEA",
        warning="#725C22",
        warning_soft="#F1ECD8",
        danger="#7B3A36",
        danger_soft="#F0E4E2",
        info="#2B2B2B",
        info_soft="#E8E8E5",
        disabled_bg="#E9E9E6",
        disabled_border="#CFCFCA",
        list_hover="#F0F0ED",
        event_item_bg="#FFFFFF",
        progress_track="#D7D7D2",
        progress_start="#6F6F6B",
        progress_end="#1F1F1F",
        progress_soft_start="#A8A8A1",
        progress_soft_end="#4B4B48",
        scrollbar="#BDBDB7",
        scrollbar_hover="#8E8E88",
        shadow="#222222",
        focus="#555555",
    ),
}


def alpha(hex_color: str, opacity: float) -> str:
    """Convert '#RRGGBB' to rgba(r, g, b, opacity)."""

    cleaned = hex_color.lstrip("#")
    red = int(cleaned[0:2], 16)
    green = int(cleaned[2:4], 16)
    blue = int(cleaned[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {opacity:.3f})"
