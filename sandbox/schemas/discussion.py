from __future__ import annotations

from typing import Any
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from sandbox.schemas.usage import TokenUsage


class DiscussionStage(str, Enum):
    INDEPENDENT_JUDGMENT = "independent_judgment"
    CROSS_QUESTION = "cross_question"
    REVISED_PLAN = "revised_plan"
    FINAL_VERDICT = "final_verdict"


class ProgressEventType(str, Enum):
    SESSION_STARTED = "session_started"
    STAGE_STARTED = "stage_started"
    MEMBER_STARTED = "member_started"
    MEMBER_FINISHED = "member_finished"
    STAGE_FINISHED = "stage_finished"
    SESSION_FINISHED = "session_finished"
    SESSION_FAILED = "session_failed"


class ResultStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    DEGRADED = "degraded"
    ERROR = "error"


class SessionStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"


class Scenario(BaseModel):
    """User-provided sandbox scenario."""

    title: str = Field(min_length=1)
    background: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    friendly_forces: list[str] = Field(default_factory=list)
    enemy_forces: list[str] = Field(default_factory=list)
    objectives: list[str] = Field(default_factory=list)
    victory_conditions: list[str] = Field(default_factory=list)
    additional_notes: list[str] = Field(default_factory=list)

    def to_prompt_text(self) -> str:
        sections = [
            self._render_section("标题", [self.title]),
            self._render_section("背景", [self.background]),
            self._render_section("约束条件", self.constraints),
            self._render_section("我方兵力", self.friendly_forces),
            self._render_section("敌方兵力", self.enemy_forces),
            self._render_section("目标", self.objectives),
            self._render_section("胜负条件", self.victory_conditions),
            self._render_section("补充说明", self.additional_notes),
        ]
        return "\n\n".join(section for section in sections if section)

    def to_markdown(self) -> str:
        sections = [
            f"### 标题\n{self.title}",
            f"### 背景\n{self.background}",
            self._render_markdown_section("约束条件", self.constraints),
            self._render_markdown_section("我方兵力", self.friendly_forces),
            self._render_markdown_section("敌方兵力", self.enemy_forces),
            self._render_markdown_section("目标", self.objectives),
            self._render_markdown_section("胜负条件", self.victory_conditions),
            self._render_markdown_section("补充说明", self.additional_notes),
        ]
        return "\n\n".join(section for section in sections if section)

    @staticmethod
    def _render_section(title: str, items: list[str]) -> str:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if not cleaned:
            return ""
        body = "\n".join(f"- {item}" for item in cleaned)
        return f"{title}:\n{body}"

    @staticmethod
    def _render_markdown_section(title: str, items: list[str]) -> str:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if not cleaned:
            return ""
        body = "\n".join(f"- {item}" for item in cleaned)
        return f"### {title}\n{body}"


class CrossQuestionAssignment(BaseModel):
    member_id: str
    member_name: str
    target_member_id: str
    target_member_name: str
    reason: str


class AgentTurnResult(BaseModel):
    """One agent's output for one stage."""

    agent_id: str
    agent_name: str
    model: str
    skill_id: str | None = None
    skill_ids: list[str] = Field(default_factory=list)
    token_usage: TokenUsage | None = None
    stage: DiscussionStage
    status: ResultStatus = ResultStatus.SUCCESS
    content: str = ""
    error: str | None = None
    target_member_id: str | None = None
    target_member_name: str | None = None
    started_at: datetime
    finished_at: datetime
    latency_ms: int


class RoundResult(BaseModel):
    """One fixed discussion stage in the full workflow."""

    stage: DiscussionStage
    status: ResultStatus = ResultStatus.SUCCESS
    moderator_note: str | None = None
    assignments: list[CrossQuestionAssignment] = Field(default_factory=list)
    member_results: list[AgentTurnResult] = Field(default_factory=list)
    judge_result: AgentTurnResult | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class SessionRecord(BaseModel):
    """The complete discussion session, persisted to local JSON."""

    session_id: str
    config_id: str
    config_name: str
    scenario: Scenario
    rounds: list[RoundResult] = Field(default_factory=list)
    member_memories: dict[str, list[str]] = Field(default_factory=dict)
    status: SessionStatus = SessionStatus.RUNNING
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    markdown_summary: str = ""
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    created_at: datetime
    completed_at: datetime | None = None


class SessionSummary(BaseModel):
    """Lightweight session metadata for history and replay lists."""

    session_id: str
    title: str
    config_name: str
    status: str
    source_path: str
    created_at: datetime | None = None
    completed_at: datetime | None = None
    round_count: int = 0
    member_count: int = 0
    error: str | None = None


class DiscussionProgressEvent(BaseModel):
    """Progress event emitted during discussion execution."""

    event_type: ProgressEventType
    session_id: str
    created_at: datetime
    stage: DiscussionStage | None = None
    scenario_title: str | None = None
    config_name: str | None = None
    member_id: str | None = None
    member_name: str | None = None
    status: str | None = None
    error: str | None = None
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class MemberRuntimeOverride(BaseModel):
    """Runtime member model and skill selection from the desktop form."""

    member_id: str = Field(min_length=1)
    model: str | None = None
    skills: list[str] = Field(default_factory=list)

    @field_validator("member_id")
    @classmethod
    def normalize_member_id(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("member_id cannot be empty.")
        return text

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized


class RunDiscussionRequest(BaseModel):
    config_name: str = "roundtable.example.yaml"
    scenario: Scenario
    member_overrides: list[MemberRuntimeOverride] = Field(default_factory=list)


class RunDiscussionResponse(BaseModel):
    session_id: str
    session: SessionRecord
    markdown: str
