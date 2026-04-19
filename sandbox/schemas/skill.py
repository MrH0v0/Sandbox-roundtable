from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _normalize_list_items(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items

    items: list[str] = []
    for line in str(value).splitlines():
        cleaned = line.strip().lstrip("-").strip()
        if cleaned:
            items.append(cleaned)
    return items


class SkillSupportingFile(BaseModel):
    """Text file bundled with a folder-based skill."""

    path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    truncated: bool = False


class SkillDefinition(BaseModel):
    """Validated skill data loaded from markdown/json/yaml files."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = "未分类"
    core_strategy: str = Field(min_length=1)
    decision_priorities: list[str] = Field(min_length=1)
    risk_preference: str = Field(min_length=1)
    information_view: str = Field(min_length=1)
    tempo_view: str = Field(min_length=1)
    resource_view: str = Field(min_length=1)
    common_failure_modes: list[str] = Field(min_length=1)
    output_format_requirements: list[str] = Field(min_length=1)
    source_file: str = Field(min_length=1)
    description: str | None = None
    notes: str | None = None
    supporting_files: list[SkillSupportingFile] = Field(default_factory=list)

    @field_validator(
        "decision_priorities",
        "common_failure_modes",
        "output_format_requirements",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: str | list[str]) -> list[str]:
        normalized = _normalize_list_items(value)
        if not normalized:
            raise ValueError("List field must contain at least one non-empty item.")
        return normalized

    @field_validator(
        "id",
        "name",
        "category",
        "core_strategy",
        "risk_preference",
        "information_view",
        "tempo_view",
        "resource_view",
        "source_file",
    )
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Field cannot be empty.")
        return text

    def to_prompt_block(self) -> str:
        """Render the skill as a readable prompt block for model injection."""

        def bullet_list(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items)

        lines = [
            f"Skill 名称: {self.name}",
            f"Skill ID: {self.id}",
            f"核心战略观:\n{self.core_strategy}",
            f"决策优先级:\n{bullet_list(self.decision_priorities)}",
            f"风险偏好:\n{self.risk_preference}",
            f"信息观:\n{self.information_view}",
            f"节奏观:\n{self.tempo_view}",
            f"资源观:\n{self.resource_view}",
            f"常见失败模式:\n{bullet_list(self.common_failure_modes)}",
            f"输出格式要求:\n{bullet_list(self.output_format_requirements)}",
        ]

        if self.notes:
            lines.append(f"维护备注:\n{self.notes.strip()}")

        if self.supporting_files:
            supporting_blocks = []
            for file in self.supporting_files:
                suffix = "\n[truncated]" if file.truncated else ""
                supporting_blocks.append(f"[{file.path}]\n{file.content}{suffix}")
            lines.append("Skill folder supporting context:\n" + "\n\n".join(supporting_blocks))

        return "\n\n".join(lines)
