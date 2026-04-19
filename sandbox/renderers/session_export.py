from __future__ import annotations

import re

from sandbox.renderers.markdown import session_markdown_for_display
from sandbox.schemas.discussion import SessionRecord


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_LIST_RE = re.compile(r"^(\s*)(?:[-*+]\s+|\d+[.)]\s+)(.+)$")
_EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)")
_FILENAME_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_FILENAME_SPACES_RE = re.compile(r"\s+")


def get_export_markdown_for_session(session: SessionRecord) -> str:
    """Return the normalized Markdown document used for display and export."""

    return session_markdown_for_display(session).strip() + "\n"


def get_export_text_for_session(session: SessionRecord) -> str:
    markdown = get_export_markdown_for_session(session)
    return markdown_to_plain_text(markdown)


def suggest_session_export_filename(session: SessionRecord, extension: str) -> str:
    clean_extension = extension.strip().lstrip(".") or "md"
    title = _sanitize_filename_part(session.scenario.title) or "session"
    session_part = session.session_id.strip()[:8] or "unknown"
    return f"{title}_session_{session_part}.{clean_extension}"


def markdown_to_plain_text(markdown: str) -> str:
    lines: list[str] = []
    in_code_block = False

    for raw_line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            _append_blank_if_needed(lines)
            continue

        if in_code_block:
            lines.append(line)
            continue

        if not stripped:
            _append_blank_if_needed(lines)
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            _append_blank_if_needed(lines)
            lines.append(heading.group(2).strip())
            lines.append("")
            continue

        list_item = _LIST_RE.match(line)
        if list_item:
            indent = list_item.group(1)
            body = _clean_inline_markdown(list_item.group(2).strip())
            lines.append(f"{indent}- {body}")
            continue

        lines.append(_clean_inline_markdown(stripped))

    return _join_text_lines(lines)


def _sanitize_filename_part(value: str) -> str:
    cleaned = _FILENAME_UNSAFE_RE.sub("_", str(value or "").strip())
    cleaned = _FILENAME_SPACES_RE.sub("_", cleaned)
    cleaned = cleaned.strip(" ._")
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip(" ._")
    return cleaned


def _clean_inline_markdown(value: str) -> str:
    text = _EMPHASIS_RE.sub("", value)
    text = text.replace("`", "")
    return text.strip()


def _append_blank_if_needed(lines: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")


def _join_text_lines(lines: list[str]) -> str:
    output: list[str] = []
    blank = False
    for raw_line in lines:
        line = str(raw_line).rstrip()
        if not line:
            if output and not blank:
                output.append("")
            blank = True
            continue
        output.append(line)
        blank = False
    return "\n".join(output).strip() + "\n"
