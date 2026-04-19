from __future__ import annotations

import re

from sandbox.schemas.discussion import DiscussionStage, RoundResult, SessionRecord


STAGE_LABELS = {
    DiscussionStage.INDEPENDENT_JUDGMENT: "第一阶段：独立判断",
    DiscussionStage.CROSS_QUESTION: "第二阶段：交叉质疑",
    DiscussionStage.REVISED_PLAN: "第三阶段：修正方案",
    DiscussionStage.FINAL_VERDICT: "第四阶段：最终裁决",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;])\s+")


def render_session_markdown(session: SessionRecord) -> str:
    """Create a readable markdown replay document from the stored session."""

    lines = [
        f"# {session.scenario.title.strip() or f'Session {session.session_id}'}",
        "",
        "## 基本信息",
        "",
        f"- 配置: {session.config_name}",
        f"- Session ID: {session.session_id}",
        f"- 状态: {_value_text(session.status)}",
        f"- 阶段数: {len(session.rounds)}",
        f"- 创建时间: {session.created_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    if session.completed_at is not None:
        lines.append(
            f"- 完成时间: {session.completed_at.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

    warnings = [warning.strip() for warning in session.warnings if warning and warning.strip()]
    if session.error:
        warnings.append(session.error.strip())
    if warnings:
        lines.extend(["", "## 运行提示", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## 场景", "", _render_scenario_markdown(session.scenario)])

    discussion_rounds = [
        round_result
        for round_result in session.rounds
        if round_result.stage != DiscussionStage.FINAL_VERDICT
    ]
    final_rounds = [
        round_result
        for round_result in session.rounds
        if round_result.stage == DiscussionStage.FINAL_VERDICT
    ]

    if discussion_rounds:
        lines.extend(["", "## 讨论过程", ""])
        for round_result in discussion_rounds:
            lines.extend(_render_round(round_result))

    if final_rounds:
        lines.extend(["", "## 最终结论 / 复盘摘要", ""])
        for round_result in final_rounds:
            lines.extend(_render_round(round_result, include_stage_heading=False))

    return _join_markdown_lines(lines)


def session_markdown_for_display(session: SessionRecord) -> str:
    if session.rounds:
        try:
            return render_session_markdown(session)
        except Exception:
            pass

    normalized = normalize_markdown_text(session.markdown_summary)
    return normalized or f"# {session.scenario.title}\n\n该 session 暂无 Markdown 内容。\n"


def normalize_markdown_text(text: str, *, minimum_heading_level: int = 1) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return ""

    output: list[str] = []
    in_code_block = False
    previous_was_list = False

    for raw_line in cleaned.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            _append_blank_if_needed(output)
            output.append(line)
            in_code_block = not in_code_block
            previous_was_list = False
            continue

        if in_code_block:
            output.append(line)
            continue

        if not stripped:
            _append_blank_if_needed(output)
            previous_was_list = False
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            _append_blank_if_needed(output)
            heading_level = max(minimum_heading_level, len(heading.group(1)))
            output.append(f"{'#' * min(6, heading_level)} {heading.group(2).strip()}")
            output.append("")
            previous_was_list = False
            continue

        if _LIST_RE.match(stripped):
            if output and output[-1] and not previous_was_list:
                output.append("")
            output.append(stripped)
            previous_was_list = True
            continue

        for paragraph in _split_long_line(stripped):
            if output and output[-1] and previous_was_list:
                output.append("")
            output.append(paragraph)
            previous_was_list = False

    return _join_markdown_lines(output)


def _render_scenario_markdown(session_scenario) -> str:
    sections = [
        ("Session 标题", [session_scenario.title]),
        ("背景", [session_scenario.background]),
        ("约束条件", session_scenario.constraints),
        ("我方兵力", session_scenario.friendly_forces),
        ("敌方兵力", session_scenario.enemy_forces),
        ("目标", session_scenario.objectives),
        ("胜负条件", session_scenario.victory_conditions),
        ("补充说明", session_scenario.additional_notes),
    ]
    lines: list[str] = []
    for title, items in sections:
        cleaned_items = [str(item).strip() for item in items if str(item).strip()]
        if not cleaned_items:
            continue
        lines.extend([f"### {title}", ""])
        if len(cleaned_items) == 1 and title in {"Session 标题", "背景"}:
            lines.extend(_split_long_line(cleaned_items[0]))
        else:
            lines.extend(f"- {item}" for item in cleaned_items)
        lines.append("")
    return _join_markdown_lines(lines)


def _render_round(
    round_result: RoundResult,
    *,
    include_stage_heading: bool = True,
) -> list[str]:
    lines: list[str] = []
    if include_stage_heading:
        lines.extend([f"### {_render_round_header(round_result)}", ""])

    if round_result.moderator_note:
        lines.extend(["#### 主持人说明", ""])
        lines.append(normalize_markdown_text(round_result.moderator_note, minimum_heading_level=5))

    if round_result.assignments:
        lines.extend(["#### 质疑分配", ""])
        for assignment in round_result.assignments:
            lines.append(
                f"- {assignment.member_name} -> {assignment.target_member_name}: {assignment.reason}"
            )
        lines.append("")

    for result in round_result.member_results:
        lines.extend(_render_member_result(result))

    if round_result.judge_result:
        lines.extend(_render_member_result(round_result.judge_result, heading="Judge"))

    if round_result.warnings:
        lines.extend(["#### 本阶段提示", ""])
        lines.extend(f"- {warning}" for warning in round_result.warnings if warning)
        lines.append("")

    return lines


def _render_round_header(round_result: RoundResult) -> str:
    return STAGE_LABELS.get(round_result.stage, round_result.stage.value)


def _render_member_result(result, *, heading: str | None = None) -> list[str]:
    title = heading or result.agent_name
    lines = [
        f"#### {title}",
        "",
        f"- 状态: {_value_text(result.status)}",
        f"- 模型: {result.model}",
    ]
    skill_ids = getattr(result, "skill_ids", []) or []
    if len(skill_ids) > 1:
        lines.append(f"- Skills: {', '.join(skill_ids)}")
    elif skill_ids:
        lines.append(f"- Skill: {skill_ids[0]}")
    elif result.skill_id:
        lines.append(f"- Skill: {result.skill_id}")
    if result.target_member_name:
        lines.append(f"- 指向成员: {result.target_member_name}")

    body = result.content if _value_text(result.status) != "error" else result.error or ""
    if not body:
        body = "该角色本阶段没有可展示内容。"
    lines.extend(["", normalize_markdown_text(body, minimum_heading_level=5), ""])
    return lines


def _split_long_line(line: str) -> list[str]:
    if len(line) <= 220:
        return [line]

    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(line) if part.strip()]
    if len(sentences) <= 1:
        return [line]

    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > 160:
            paragraphs.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        paragraphs.append(current)
    return paragraphs or [line]


def _append_blank_if_needed(lines: list[str]) -> None:
    if lines and lines[-1] != "":
        lines.append("")


def _join_markdown_lines(lines: list[str]) -> str:
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


def _value_text(value: object) -> str:
    return str(getattr(value, "value", value))
