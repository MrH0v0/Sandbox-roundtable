from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import yaml

from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import RoundtableEngine
from sandbox.renderers import markdown as markdown_renderer
from sandbox.renderers.markdown import render_session_markdown
from sandbox.renderers.session_export import (
    get_export_markdown_for_session,
    get_export_text_for_session,
    suggest_session_export_filename,
)
from sandbox.schemas.discussion import (
    AgentTurnResult,
    DiscussionStage,
    MemberRuntimeOverride,
    ProgressEventType,
    ResultStatus,
    RoundResult,
    Scenario,
    SessionRecord,
    SessionStatus,
)
from sandbox.schemas.usage import ChatCompletionResult, TokenUsage
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


class FakeAIClient:
    def __init__(self, *, fail_models: set[str] | None = None) -> None:
        self.active_calls = 0
        self.max_active_calls = 0
        self.fail_models = fail_models or set()
        self.calls: list[dict] = []

    async def chat_completion(self, *, model: str, messages, generation) -> str:
        self.calls.append({"model": model, "messages": messages})
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.02)
            if model in self.fail_models:
                raise RuntimeError("planned member failure")
            return f"{model} response"
        finally:
            self.active_calls -= 1


class UsageAIClient(FakeAIClient):
    async def chat_completion(self, *, model: str, messages, generation) -> ChatCompletionResult:
        self.calls.append({"model": model, "messages": messages})
        return ChatCompletionResult(
            content=f"{model} response",
            usage=TokenUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        )


def _write_skill(path: Path, skill_id: str) -> None:
    path.write_text(
        f"""---
id: {skill_id}
name: "{skill_id}"
core_strategy: "strategy"
decision_priorities:
  - "priority"
risk_preference: "medium"
information_view: "info"
tempo_view: "tempo"
resource_view: "resource"
common_failure_modes:
  - "failure"
output_format_requirements:
  - "format"
---
""",
        encoding="utf-8",
    )


def _write_folder_skill(path: Path, skill_id: str) -> None:
    references_dir = path / "references"
    scripts_dir = path / "scripts"
    references_dir.mkdir(parents=True)
    scripts_dir.mkdir()
    (path / "SKILL.md").write_text(
        f"""---
id: {skill_id}
name: "Folder Debate"
description: "Use the local folder workflow."
category: "辩论"
---

Follow the folder debate workflow.
""",
        encoding="utf-8",
    )
    (references_dir / "playbook.md").write_text(
        "Use the reference playbook before answering.",
        encoding="utf-8",
    )
    (scripts_dir / "score.py").write_text(
        "def score(argument):\n    return len(argument)\n",
        encoding="utf-8",
    )


def test_session_markdown_renderer_normalizes_member_blocks() -> None:
    timestamp = datetime.now(timezone.utc)
    session = SessionRecord(
        session_id="format-session",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(
            title="Format Scenario",
            background="第一段背景。第二段背景。第三段背景。",
            constraints=["约束 A", "约束 B"],
        ),
        status=SessionStatus.COMPLETED,
        created_at=timestamp,
        completed_at=timestamp,
        rounds=[
            RoundResult(
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                status=ResultStatus.SUCCESS,
                member_results=[
                    AgentTurnResult(
                        agent_id="member-a",
                        agent_name="Member A",
                        model="model-a",
                        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                        status=ResultStatus.SUCCESS,
                        content="## 局势判断\n第一段判断。第二段判断。\n- 风险 A\n- 风险 B",
                        started_at=timestamp,
                        finished_at=timestamp,
                        latency_ms=12,
                    )
                ],
                started_at=timestamp,
                finished_at=timestamp,
            ),
            RoundResult(
                stage=DiscussionStage.FINAL_VERDICT,
                status=ResultStatus.SUCCESS,
                judge_result=AgentTurnResult(
                    agent_id="judge",
                    agent_name="Judge",
                    model="judge-model",
                    stage=DiscussionStage.FINAL_VERDICT,
                    status=ResultStatus.SUCCESS,
                    content="## Consensus\n结论正文。\n## Recommended Action\n- 行动 A",
                    started_at=timestamp,
                    finished_at=timestamp,
                    latency_ms=15,
                ),
                started_at=timestamp,
                finished_at=timestamp,
            ),
        ],
    )

    markdown = render_session_markdown(session)

    assert markdown.startswith("# Format Scenario")
    assert "## 基本信息" in markdown
    assert "- 配置: demo.yaml" in markdown
    assert "- 阶段数: 2" in markdown
    assert "## 场景" in markdown
    assert "## 讨论过程" in markdown
    assert "### 第一阶段：独立判断" in markdown
    assert "#### Member A" in markdown
    assert "- 状态: success\n- 模型: model-a\n\n##### 局势判断" in markdown
    assert "\n- 风险 A\n- 风险 B\n" in markdown
    assert "## 最终结论 / 复盘摘要" in markdown
    assert "#### Judge" in markdown
    assert "- 状态: success\n- 模型: judge-model\n\n##### Consensus" in markdown
    assert "\n##### Recommended Action\n\n- 行动 A" in markdown


def test_session_markdown_for_display_rerenders_structured_sessions() -> None:
    timestamp = datetime.now(timezone.utc)
    session = SessionRecord(
        session_id="display-session",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Display Scenario", background="Background"),
        status=SessionStatus.COMPLETED,
        markdown_summary="# stale summary\ncompressed",
        created_at=timestamp,
        completed_at=timestamp,
        rounds=[
            RoundResult(
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                status=ResultStatus.SUCCESS,
                member_results=[
                    AgentTurnResult(
                        agent_id="member-a",
                        agent_name="Member A",
                        model="model-a",
                        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                        content="## 判断\n正文。",
                        started_at=timestamp,
                        finished_at=timestamp,
                        latency_ms=1,
                    )
                ],
                started_at=timestamp,
                finished_at=timestamp,
            )
        ],
    )

    display_markdown = markdown_renderer.session_markdown_for_display(session)

    assert "# stale summary" not in display_markdown
    assert "# Display Scenario" in display_markdown
    assert "## 讨论过程" in display_markdown


def test_session_export_uses_normalized_markdown_and_readable_text() -> None:
    timestamp = datetime(2026, 4, 18, 9, 30, tzinfo=timezone.utc)
    session = SessionRecord(
        session_id="dc86e914-long-session-id",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(
            title="中国大陆武统台湾:/?*",
            background="Background",
            constraints=["保持克制", "优先验证"],
        ),
        status=SessionStatus.COMPLETED,
        markdown_summary="# stale summary\ncompressed",
        created_at=timestamp,
        completed_at=timestamp,
        rounds=[
            RoundResult(
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                status=ResultStatus.SUCCESS,
                member_results=[
                    AgentTurnResult(
                        agent_id="member-a",
                        agent_name="Member A",
                        model="model-a",
                        stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                        content="## 判断\n正文。\n- 要点 A",
                        started_at=timestamp,
                        finished_at=timestamp,
                        latency_ms=1,
                    )
                ],
                started_at=timestamp,
                finished_at=timestamp,
            )
        ],
    )

    markdown = get_export_markdown_for_session(session)
    text = get_export_text_for_session(session)

    assert "# stale summary" not in markdown
    assert "# 中国大陆武统台湾:/?*" in markdown
    assert "## 基本信息" in markdown
    assert "## 场景" in markdown
    assert "## 讨论过程" in markdown
    assert "#### Member A" in markdown
    assert "##### 判断" in markdown
    assert "- 要点 A" in markdown
    assert "中国大陆武统台湾:/?*" in text
    assert "基本信息" in text
    assert "讨论过程" in text
    assert "Member A" in text
    assert "要点 A" in text
    assert "# " not in text
    assert len(text.splitlines()) > 8

    assert suggest_session_export_filename(session, "md") == (
        "中国大陆武统台湾_session_dc86e914.md"
    )
    assert suggest_session_export_filename(session, ".txt").endswith(".txt")


def test_config_summary_exposes_members_models_and_skill_catalog(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    skills_dir.mkdir()
    configs_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    (skills_dir / "beta.yaml").write_text(
        """id: beta
name: "Beta"
category: "分析"
core_strategy: "strategy"
decision_priorities:
  - "priority"
risk_preference: "medium"
information_view: "info"
tempo_view: "tempo"
resource_view: "resource"
common_failure_modes:
  - "failure"
output_format_requirements:
  - "format"
""",
        encoding="utf-8",
    )
    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "model-a",
                        "skills": ["alpha.md", "beta.yaml"],
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "model-b",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))

    config = loader.load("demo.yaml")
    summaries = loader.list_summaries()

    assert config.members[0].skill_references == ["alpha.md", "beta.yaml"]
    assert config.members[1].skill_references == []
    assert summaries[0].members[0].skills == ["alpha.md", "beta.yaml"]
    assert summaries[0].members[1].skills == []
    assert summaries[0].available_models == [
        "judge-model",
        "model-a",
        "model-b",
        "moderator-model",
    ]
    assert {skill.category for skill in summaries[0].skills} == {"未分类", "分析"}


async def test_roundtable_engine_is_concurrent_and_tolerates_member_failure(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")
    _write_skill(skills_dir / "gamma.md", "gamma")

    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "model-bad",
                        "skill": "beta.md",
                    },
                    {
                        "id": "member-c",
                        "display_name": "Member C",
                        "model": "model-c",
                        "skill": "gamma.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    config_loader = RoundtableConfigLoader(configs_dir, skill_loader)
    session_store = SessionStore(sessions_dir)
    fake_client = FakeAIClient(fail_models={"model-bad"})
    engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=fake_client,
        session_store=session_store,
    )

    scenario = Scenario(
        title="Test Scenario",
        background="Background",
        constraints=["Constraint"],
        friendly_forces=["Friendly"],
        enemy_forces=["Enemy"],
        objectives=["Objective"],
        victory_conditions=["Victory"],
    )

    session = await engine.run_full_discussion(
        scenario=scenario,
        config_name="demo.yaml",
    )

    assert len(session.rounds) == 4
    assert session.status == "degraded"
    assert fake_client.max_active_calls >= 2
    assert len(session.rounds[0].member_results) == 3
    assert any(result.status == "error" for result in session.rounds[0].member_results)
    assert len(session.rounds[1].member_results) == 3
    assert len(session.rounds[2].member_results) == 3
    assert (sessions_dir / f"{session.session_id}.json").exists()
    assert session_store.list_summaries()[0].status == "degraded"


async def test_roundtable_engine_applies_member_runtime_model_and_skills(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "config-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "config-b",
                        "skill": "beta.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    config_loader = RoundtableConfigLoader(configs_dir, skill_loader)
    session_store = SessionStore(sessions_dir)
    fake_client = FakeAIClient()
    engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=fake_client,
        session_store=session_store,
    )

    scenario = Scenario(
        title="Runtime Scenario",
        background="Background",
        constraints=["Constraint"],
        friendly_forces=["Friendly"],
        enemy_forces=["Enemy"],
        objectives=["Objective"],
        victory_conditions=["Victory"],
    )

    session = await engine.run_full_discussion(
        scenario=scenario,
        config_name="demo.yaml",
        member_overrides=[
            MemberRuntimeOverride(
                member_id="member-a",
                model="runtime-a",
                skills=["alpha.md", "beta.md"],
            ),
            MemberRuntimeOverride(
                member_id="member-b",
                model="runtime-b",
                skills=[],
            ),
        ],
    )

    stage_one_by_member = {
        result.agent_id: result for result in session.rounds[0].member_results
    }
    assert stage_one_by_member["member-a"].model == "runtime-a"
    assert stage_one_by_member["member-a"].skill_ids == ["alpha", "beta"]
    assert stage_one_by_member["member-b"].model == "runtime-b"
    assert stage_one_by_member["member-b"].skill_ids == []
    assert "- Skills: alpha, beta" in session.markdown_summary

    runtime_a_prompts = [
        call["messages"][0]["content"]
        for call in fake_client.calls
        if call["model"] == "runtime-a"
    ]
    assert runtime_a_prompts
    assert "Skill ID: alpha" in runtime_a_prompts[0]
    assert "Skill ID: beta" in runtime_a_prompts[0]


async def test_roundtable_engine_injects_folder_skill_supporting_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    _write_folder_skill(skills_dir / "debate-kit", "debate-kit")
    _write_skill(skills_dir / "beta.md", "beta")

    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "runtime-a",
                        "skills": ["debate-kit"],
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "runtime-b",
                        "skill": "beta.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    config_loader = RoundtableConfigLoader(configs_dir, skill_loader)
    session_store = SessionStore(sessions_dir)
    fake_client = FakeAIClient()
    engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=fake_client,
        session_store=session_store,
    )

    await engine.run_full_discussion(
        scenario=Scenario(title="Folder Skill", background="Background"),
        config_name="demo.yaml",
    )

    runtime_a_prompts = [
        call["messages"][0]["content"]
        for call in fake_client.calls
        if call["model"] == "runtime-a"
    ]
    assert runtime_a_prompts
    assert "Skill ID: debate-kit" in runtime_a_prompts[0]
    assert "references/playbook.md" in runtime_a_prompts[0]
    assert "Use the reference playbook before answering." in runtime_a_prompts[0]
    assert "scripts/score.py" in runtime_a_prompts[0]
    assert "def score" in runtime_a_prompts[0]


async def test_roundtable_engine_records_token_usage_on_turn_results(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "model-b",
                        "skill": "beta.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    engine = RoundtableEngine(
        config_loader=RoundtableConfigLoader(configs_dir, skill_loader),
        skill_loader=skill_loader,
        client=UsageAIClient(),
        session_store=SessionStore(sessions_dir),
    )

    session = await engine.run_full_discussion(
        scenario=Scenario(title="Usage", background="Background"),
        config_name="demo.yaml",
    )

    first_member_result = session.rounds[0].member_results[0]
    assert first_member_result.token_usage is not None
    assert first_member_result.token_usage.total_tokens == 20
    assert session.token_usage.total_tokens == 180
    assert session.token_usage.call_count == 9


async def test_roundtable_engine_persists_failed_partial_session(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo",
                "members": [
                    {
                        "id": "member-a",
                        "display_name": "Member A",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "member-b",
                        "display_name": "Member B",
                        "model": "model-b",
                        "skill": "beta.md",
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    skill_loader = SkillLoader(skills_dir)
    config_loader = RoundtableConfigLoader(configs_dir, skill_loader)
    session_store = SessionStore(sessions_dir)
    fake_client = FakeAIClient()
    engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=fake_client,
        session_store=session_store,
    )

    scenario = Scenario(
        title="Failure Scenario",
        background="Background",
        constraints=["Constraint"],
        friendly_forces=["Friendly"],
        enemy_forces=["Enemy"],
        objectives=["Objective"],
        victory_conditions=["Victory"],
    )

    async def failing_progress_callback(event) -> None:
        if (
            event.event_type == ProgressEventType.STAGE_STARTED
            and event.stage == DiscussionStage.CROSS_QUESTION
        ):
            raise RuntimeError("planned progress callback failure")

    try:
        await engine.run_full_discussion(
            scenario=scenario,
            config_name="demo.yaml",
            progress_callback=failing_progress_callback,
        )
    except RuntimeError as exc:
        assert str(exc) == "planned progress callback failure"
    else:
        raise AssertionError("Expected discussion to fail.")

    summaries = session_store.list_summaries()
    assert len(summaries) == 1
    assert summaries[0].status == "failed"

    persisted_session = session_store.load(summaries[0].session_id)
    assert persisted_session.status == "failed"
    assert persisted_session.error == "planned progress callback failure"
    assert len(persisted_session.rounds) == 1
    assert persisted_session.markdown_summary
