from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class GenerationConfig(BaseModel):
    """LLM generation settings bound to one specific role."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1200, gt=0)
    max_tokens_parameter: Literal["auto", "max_tokens", "max_completion_tokens"] = "auto"
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)


class RoleConfig(BaseModel):
    """Base config shared by members, moderator and judge."""

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    skill: str | None = None
    skills: list[str] = Field(default_factory=list)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return [str(item).strip() for item in value if str(item).strip()]

    @property
    def skill_references(self) -> list[str]:
        references: list[str] = []
        if self.skill and self.skill.strip():
            references.append(self.skill.strip())
        references.extend(self.skills)
        deduped: list[str] = []
        for reference in references:
            if reference not in deduped:
                deduped.append(reference)
        return deduped


class MemberConfig(RoleConfig):
    """A discussion member can bind zero or more external skill files."""


class RoundtableConfig(BaseModel):
    """Top-level YAML or JSON configuration for one roundtable setup."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    members: list[MemberConfig] = Field(min_length=2)
    moderator: RoleConfig
    judge: RoleConfig

    @model_validator(mode="after")
    def validate_unique_role_ids(self) -> "RoundtableConfig":
        role_ids = [member.id for member in self.members]
        role_ids.extend([self.moderator.id, self.judge.id])
        duplicates = {role_id for role_id in role_ids if role_ids.count(role_id) > 1}
        if duplicates:
            duplicate_text = ", ".join(sorted(duplicates))
            raise ValueError(f"Role ids must be unique. Duplicates: {duplicate_text}")
        return self


class RoundtableConfigSummary(BaseModel):
    """Lightweight config metadata for config pickers."""

    config_name: str = Field(min_length=1)
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    member_count: int = Field(ge=0)
    member_names: list[str] = Field(default_factory=list)
    moderator_name: str = Field(min_length=1)
    judge_name: str = Field(min_length=1)
    members: list["MemberConfigSummary"] = Field(default_factory=list)
    available_models: list[str] = Field(default_factory=list)
    skills: list["SkillCatalogItem"] = Field(default_factory=list)
    generation_max_tokens: int = Field(default=1200, gt=0)
    generation_max_tokens_mixed: bool = False


class MemberConfigSummary(BaseModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    skills: list[str] = Field(default_factory=list)


class SkillCatalogItem(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    source_file: str = Field(min_length=1)
