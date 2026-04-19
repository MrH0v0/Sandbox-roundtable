from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from uuid import uuid4

from sandbox.agents.member import MemberAgent
from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.engines.judge import JudgeEngine
from sandbox.engines.moderator import ModeratorEngine
from sandbox.renderers.markdown import render_session_markdown
from sandbox.schemas.config import RoleConfig, RoundtableConfig
from sandbox.schemas.discussion import (
    AgentTurnResult,
    CrossQuestionAssignment,
    DiscussionProgressEvent,
    DiscussionStage,
    MemberRuntimeOverride,
    ProgressEventType,
    ResultStatus,
    RoundResult,
    Scenario,
    SessionRecord,
    SessionStatus,
)
from sandbox.schemas.usage import TokenUsage
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


ProgressCallback = Callable[
    [DiscussionProgressEvent],
    Awaitable[None] | None,
]


class RoundtableEngine:
    """Runs the fixed four-stage discussion workflow end to end."""

    def __init__(
        self,
        *,
        config_loader: RoundtableConfigLoader,
        skill_loader: SkillLoader,
        client: AIHubMixClient,
        session_store: SessionStore,
    ):
        self.config_loader = config_loader
        self.skill_loader = skill_loader
        self.client = client
        self.session_store = session_store

    async def run_full_discussion(
        self,
        *,
        scenario: Scenario,
        config_name: str,
        member_overrides: list[MemberRuntimeOverride] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SessionRecord:
        session: SessionRecord | None = None

        try:
            self.skill_loader.load_all()
            config = self.config_loader.load(config_name)
            config = self._apply_member_overrides(config, member_overrides or [])
            session = self._create_session(
                config=config,
                config_name=config_name,
                scenario=scenario,
            )

            await self._emit_progress(
                progress_callback,
                DiscussionProgressEvent(
                    event_type=ProgressEventType.SESSION_STARTED,
                    session_id=session.session_id,
                    created_at=utc_now(),
                    scenario_title=scenario.title,
                    config_name=config_name,
                    status=SessionStatus.RUNNING,
                    message="Discussion session created.",
                    data={
                        "member_count": len(config.members),
                        "members": [
                            {
                                "id": member.id,
                                "name": member.display_name,
                                "model": member.model,
                                "skills": member.skill_references,
                            }
                            for member in config.members
                        ],
                        "moderator": config.moderator.display_name,
                        "judge": config.judge.display_name,
                    },
                ),
            )

            member_agents = self._build_member_agents(config)
            moderator = self._build_moderator(config.moderator)
            judge = self._build_judge(config.judge)

            await self._emit_stage_started(
                progress_callback,
                session,
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                message="Members are preparing independent judgments.",
            )
            stage_one = await self._run_stage_one(
                session,
                scenario,
                member_agents,
                progress_callback=progress_callback,
            )
            session.rounds.append(stage_one)
            self._append_member_memory(session, stage_one.member_results)
            await self._emit_stage_finished(progress_callback, session, stage_one)

            await self._emit_stage_started(
                progress_callback,
                session,
                stage=DiscussionStage.CROSS_QUESTION,
                message="Moderator is planning cross-questions.",
            )
            moderator_stage_two_warnings: list[str] = []
            try:
                moderator_stage_two_note, assignments = await moderator.plan_cross_questions(
                    scenario=scenario,
                    members=config.members,
                    stage_one_results=stage_one.member_results,
                )
                await self._record_system_token_usage(
                    progress_callback=progress_callback,
                    session=session,
                    role_config=config.moderator,
                    stage=DiscussionStage.CROSS_QUESTION,
                    token_usage=moderator.last_token_usage,
                )
            except Exception as exc:
                moderator_stage_two_note = moderator.build_fallback_cross_question_note()
                assignments = moderator._build_round_robin_assignments(
                    config.members,
                    stage_one.member_results,
                )
                moderator_stage_two_warnings.append(
                    f"Moderator fallback used during cross-question planning: {exc}"
                )

            stage_two = await self._run_stage_two(
                session=session,
                scenario=scenario,
                member_agents=member_agents,
                stage_one_results=stage_one.member_results,
                assignments=assignments,
                moderator_note=moderator_stage_two_note,
                warnings=moderator_stage_two_warnings,
                progress_callback=progress_callback,
            )
            session.rounds.append(stage_two)
            self._append_member_memory(session, stage_two.member_results)
            await self._emit_stage_finished(progress_callback, session, stage_two)

            await self._emit_stage_started(
                progress_callback,
                session,
                stage=DiscussionStage.REVISED_PLAN,
                message="Members are revising their plans.",
            )
            moderator_stage_three_warnings: list[str] = []
            try:
                moderator_stage_three_note = await moderator.build_revision_guidance(
                    scenario=scenario,
                    stage_two_results=stage_two.member_results,
                )
                await self._record_system_token_usage(
                    progress_callback=progress_callback,
                    session=session,
                    role_config=config.moderator,
                    stage=DiscussionStage.REVISED_PLAN,
                    token_usage=moderator.last_token_usage,
                )
            except Exception as exc:
                moderator_stage_three_note = moderator.build_fallback_revision_guidance()
                moderator_stage_three_warnings.append(
                    f"Moderator fallback used during revision guidance: {exc}"
                )

            stage_three = await self._run_stage_three(
                session=session,
                scenario=scenario,
                member_agents=member_agents,
                stage_one_results=stage_one.member_results,
                stage_two_results=stage_two.member_results,
                moderator_note=moderator_stage_three_note,
                warnings=moderator_stage_three_warnings,
                progress_callback=progress_callback,
            )
            session.rounds.append(stage_three)
            self._append_member_memory(session, stage_three.member_results)
            await self._emit_stage_finished(progress_callback, session, stage_three)

            await self._emit_stage_started(
                progress_callback,
                session,
                stage=DiscussionStage.FINAL_VERDICT,
                message="Judge is preparing the final verdict.",
            )
            stage_four = await self._run_stage_four(
                session=session,
                scenario=scenario,
                judge=judge,
                stage_one_results=stage_one.member_results,
                stage_two_results=stage_two.member_results,
                stage_three_results=stage_three.member_results,
                moderator_notes=[moderator_stage_two_note, moderator_stage_three_note],
                progress_callback=progress_callback,
            )
            session.rounds.append(stage_four)
            await self._emit_stage_finished(progress_callback, session, stage_four)

            session.completed_at = utc_now()
            session.token_usage = session.token_usage.merged(
                self._collect_token_usage(session)
            )
            session.warnings = self._collect_session_warnings(session)
            session.status = self._determine_session_status(session)
            self._persist_session(session)

            await self._emit_progress(
                progress_callback,
                DiscussionProgressEvent(
                    event_type=ProgressEventType.SESSION_FINISHED,
                    session_id=session.session_id,
                    created_at=utc_now(),
                    scenario_title=scenario.title,
                    config_name=config_name,
                    status=session.status,
                    message=f"Discussion finished with status {session.status}.",
                    data={"round_count": len(session.rounds)},
                ),
            )
            return session
        except Exception as exc:
            if session is not None:
                session.completed_at = utc_now()
                session.status = SessionStatus.FAILED
                session.error = str(exc)
                session.token_usage = session.token_usage.merged(
                    self._collect_token_usage(session)
                )
                session.warnings = self._collect_session_warnings(session)
                self._persist_session(session)

                await self._emit_progress(
                    progress_callback,
                    DiscussionProgressEvent(
                        event_type=ProgressEventType.SESSION_FAILED,
                        session_id=session.session_id,
                        created_at=utc_now(),
                        scenario_title=scenario.title,
                        config_name=config_name,
                        status=SessionStatus.FAILED,
                        error=str(exc),
                        message="Discussion failed before completion.",
                        data={"round_count": len(session.rounds)},
                    ),
                )
            raise

    async def _run_stage_one(
        self,
        session: SessionRecord,
        scenario: Scenario,
        member_agents: list[MemberAgent],
        progress_callback: ProgressCallback | None = None,
    ) -> RoundResult:
        stage_started_at = utc_now()
        tasks = [
            self._safe_member_call(
                session_id=session.session_id,
                member=member,
                stage=DiscussionStage.INDEPENDENT_JUDGMENT,
                call=lambda current_member=member: current_member.independent_judgment(
                    scenario=scenario,
                    memory_entries=session.member_memories[current_member.role_config.id],
                ),
                progress_callback=progress_callback,
            )
            for member in member_agents
        ]
        results = await asyncio.gather(*tasks)
        round_warnings: list[str] = []
        return RoundResult(
            stage=DiscussionStage.INDEPENDENT_JUDGMENT,
            status=self._derive_round_status(results, warnings=round_warnings),
            member_results=results,
            warnings=round_warnings,
            started_at=stage_started_at,
            finished_at=utc_now(),
        )

    async def _run_stage_two(
        self,
        *,
        session: SessionRecord,
        scenario: Scenario,
        member_agents: list[MemberAgent],
        stage_one_results: list[AgentTurnResult],
        assignments: list[CrossQuestionAssignment],
        moderator_note: str,
        warnings: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RoundResult:
        stage_started_at = utc_now()
        result_by_member_id = {result.agent_id: result for result in stage_one_results}
        assignment_by_member_id = {assignment.member_id: assignment for assignment in assignments}

        tasks = []
        for member in member_agents:
            assignment = assignment_by_member_id[member.role_config.id]
            target_result = result_by_member_id[assignment.target_member_id]
            tasks.append(
                self._safe_member_call(
                    session_id=session.session_id,
                    member=member,
                    stage=DiscussionStage.CROSS_QUESTION,
                    target_assignment=assignment,
                    call=lambda current_member=member, current_assignment=assignment, current_target=target_result: current_member.cross_question(
                        scenario=scenario,
                        assignment=current_assignment,
                        target_stage_one_result=current_target,
                        moderator_note=moderator_note,
                        memory_entries=session.member_memories[current_member.role_config.id],
                    ),
                    progress_callback=progress_callback,
                )
            )

        results = await asyncio.gather(*tasks)
        round_warnings = [warning for warning in (warnings or []) if warning]
        return RoundResult(
            stage=DiscussionStage.CROSS_QUESTION,
            status=self._derive_round_status(results, warnings=round_warnings),
            moderator_note=moderator_note,
            assignments=assignments,
            member_results=results,
            warnings=round_warnings,
            started_at=stage_started_at,
            finished_at=utc_now(),
        )

    async def _run_stage_three(
        self,
        *,
        session: SessionRecord,
        scenario: Scenario,
        member_agents: list[MemberAgent],
        stage_one_results: list[AgentTurnResult],
        stage_two_results: list[AgentTurnResult],
        moderator_note: str,
        warnings: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RoundResult:
        stage_started_at = utc_now()
        stage_one_by_member = {result.agent_id: result for result in stage_one_results}
        critiques_by_target: dict[str, list[AgentTurnResult]] = {
            member.role_config.id: [] for member in member_agents
        }

        for result in stage_two_results:
            if result.target_member_id:
                critiques_by_target.setdefault(result.target_member_id, []).append(result)

        tasks = []
        for member in member_agents:
            stage_one_result = stage_one_by_member[member.role_config.id]
            critiques_received = critiques_by_target.get(member.role_config.id, [])
            tasks.append(
                self._safe_member_call(
                    session_id=session.session_id,
                    member=member,
                    stage=DiscussionStage.REVISED_PLAN,
                    call=lambda current_member=member, current_stage_one=stage_one_result, current_critiques=critiques_received: current_member.revised_plan(
                        scenario=scenario,
                        stage_one_result=current_stage_one,
                        critiques_received=current_critiques,
                        moderator_note=moderator_note,
                        memory_entries=session.member_memories[current_member.role_config.id],
                    ),
                    progress_callback=progress_callback,
                )
            )

        results = await asyncio.gather(*tasks)
        round_warnings = [warning for warning in (warnings or []) if warning]
        return RoundResult(
            stage=DiscussionStage.REVISED_PLAN,
            status=self._derive_round_status(results, warnings=round_warnings),
            moderator_note=moderator_note,
            member_results=results,
            warnings=round_warnings,
            started_at=stage_started_at,
            finished_at=utc_now(),
        )

    async def _run_stage_four(
        self,
        *,
        session: SessionRecord,
        scenario: Scenario,
        judge: JudgeEngine,
        stage_one_results: list[AgentTurnResult],
        stage_two_results: list[AgentTurnResult],
        stage_three_results: list[AgentTurnResult],
        moderator_notes: list[str],
        progress_callback: ProgressCallback | None = None,
    ) -> RoundResult:
        stage_started_at = utc_now()
        judge_result = await self._safe_role_call(
            session_id=session.session_id,
            role=judge,
            stage=DiscussionStage.FINAL_VERDICT,
            call=lambda: judge.render_final_verdict(
                scenario=scenario,
                stage_one_results=stage_one_results,
                stage_two_results=stage_two_results,
                stage_three_results=stage_three_results,
                moderator_notes=moderator_notes,
            ),
            fallback_call=lambda exc: judge.build_fallback_verdict(
                stage_one_results,
                stage_two_results,
                stage_three_results,
            ),
            progress_callback=progress_callback,
        )
        round_warnings: list[str] = []
        if judge_result.status == ResultStatus.DEGRADED:
            round_warnings.append(
                f"Judge fallback used during final verdict: {judge_result.error}"
            )

        return RoundResult(
            stage=DiscussionStage.FINAL_VERDICT,
            status=self._derive_round_status(
                [],
                judge_result=judge_result,
                warnings=round_warnings,
            ),
            judge_result=judge_result,
            warnings=round_warnings,
            started_at=stage_started_at,
            finished_at=utc_now(),
        )

    async def _safe_member_call(
        self,
        *,
        session_id: str,
        member: MemberAgent,
        stage: DiscussionStage,
        call: Callable[[], Awaitable[str]],
        target_assignment: CrossQuestionAssignment | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentTurnResult:
        started_at = utc_now()
        started_perf = time.perf_counter()
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.MEMBER_STARTED,
                session_id=session_id,
                created_at=started_at,
                stage=stage,
                member_id=member.role_config.id,
                member_name=member.role_config.display_name,
                status=ResultStatus.RUNNING,
                message=f"{member.role_config.display_name} started {stage.value}.",
                data={
                    "model": member.role_config.model,
                    "skill_ids": member.skill_ids,
                },
            ),
        )

        try:
            content = await call()
            status = ResultStatus.SUCCESS
            error = None
        except Exception as exc:
            content = ""
            status = ResultStatus.ERROR
            error = str(exc)

        finished_at = utc_now()
        latency_ms = int((time.perf_counter() - started_perf) * 1000)
        token_usage = member.last_token_usage
        result = AgentTurnResult(
            agent_id=member.role_config.id,
            agent_name=member.role_config.display_name,
            model=member.role_config.model,
            skill_id=member.skill_id,
            skill_ids=member.skill_ids,
            token_usage=token_usage,
            stage=stage,
            status=status,
            content=content,
            error=error,
            target_member_id=target_assignment.target_member_id if target_assignment else None,
            target_member_name=target_assignment.target_member_name if target_assignment else None,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
        )
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.MEMBER_FINISHED,
                session_id=session_id,
                created_at=finished_at,
                stage=stage,
                member_id=member.role_config.id,
                member_name=member.role_config.display_name,
                status=status,
                error=error,
                message=f"{member.role_config.display_name} finished {stage.value}.",
                data={
                    "latency_ms": latency_ms,
                    "model": member.role_config.model,
                    "skill_ids": member.skill_ids,
                    "token_usage": token_usage.model_dump(mode="json")
                    if token_usage
                    else None,
                },
            ),
        )
        return result

    async def _safe_role_call(
        self,
        *,
        session_id: str,
        role,
        stage: DiscussionStage,
        call: Callable[[], Awaitable[str]],
        fallback_call: Callable[[Exception], str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentTurnResult:
        started_at = utc_now()
        started_perf = time.perf_counter()
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.MEMBER_STARTED,
                session_id=session_id,
                created_at=started_at,
                stage=stage,
                member_id=role.role_config.id,
                member_name=role.role_config.display_name,
                status=ResultStatus.RUNNING,
                message=f"{role.role_config.display_name} started {stage.value}.",
                data={"model": role.role_config.model, "role_kind": "system"},
            ),
        )

        try:
            content = await call()
            status = ResultStatus.SUCCESS
            error = None
        except Exception as exc:
            error = str(exc)
            if fallback_call is not None:
                content = fallback_call(exc)
                status = ResultStatus.DEGRADED
            else:
                content = ""
                status = ResultStatus.ERROR

        finished_at = utc_now()
        latency_ms = int((time.perf_counter() - started_perf) * 1000)
        token_usage = role.last_token_usage
        result = AgentTurnResult(
            agent_id=role.role_config.id,
            agent_name=role.role_config.display_name,
            model=role.role_config.model,
            skill_id=role.skill_id,
            skill_ids=role.skill_ids,
            token_usage=token_usage,
            stage=stage,
            status=status,
            content=content,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
        )
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.MEMBER_FINISHED,
                session_id=session_id,
                created_at=finished_at,
                stage=stage,
                member_id=role.role_config.id,
                member_name=role.role_config.display_name,
                status=status,
                error=error,
                message=f"{role.role_config.display_name} finished {stage.value}.",
                data={
                    "latency_ms": latency_ms,
                    "model": role.role_config.model,
                    "role_kind": "system",
                    "token_usage": token_usage.model_dump(mode="json")
                    if token_usage
                    else None,
                },
            ),
        )
        return result

    def _create_session(
        self,
        *,
        config: RoundtableConfig,
        config_name: str,
        scenario: Scenario,
    ) -> SessionRecord:
        return SessionRecord(
            session_id=uuid4().hex,
            config_id=config.id,
            config_name=config_name,
            scenario=scenario,
            member_memories={member.id: [] for member in config.members},
            status=SessionStatus.RUNNING,
            created_at=utc_now(),
        )

    async def _record_system_token_usage(
        self,
        *,
        progress_callback: ProgressCallback | None,
        session: SessionRecord,
        role_config: RoleConfig,
        stage: DiscussionStage,
        token_usage: TokenUsage | None,
    ) -> None:
        if token_usage is None:
            return

        session.token_usage = session.token_usage.merged(token_usage)
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.MEMBER_FINISHED,
                session_id=session.session_id,
                created_at=utc_now(),
                stage=stage,
                member_id=role_config.id,
                member_name=role_config.display_name,
                status=ResultStatus.SUCCESS,
                message=f"{role_config.display_name} recorded token usage for {stage.value}.",
                data={
                    "model": role_config.model,
                    "role_kind": "system",
                    "token_usage": token_usage.model_dump(mode="json"),
                },
            ),
        )

    def _apply_member_overrides(
        self,
        config: RoundtableConfig,
        member_overrides: list[MemberRuntimeOverride],
    ) -> RoundtableConfig:
        if not member_overrides:
            return config

        member_ids = {member.id for member in config.members}
        override_by_member = {
            override.member_id: override for override in member_overrides
        }
        unknown_ids = sorted(set(override_by_member) - member_ids)
        if unknown_ids:
            unknown_text = ", ".join(unknown_ids)
            raise ValueError(f"Unknown member override ids: {unknown_text}")

        updated_members = []
        for member in config.members:
            override = override_by_member.get(member.id)
            if override is None:
                updated_members.append(member)
                continue

            update = {
                "skill": None,
                "skills": override.skills,
            }
            if override.model:
                update["model"] = override.model

            updated_members.append(member.model_copy(update=update))

        return config.model_copy(update={"members": updated_members})

    @staticmethod
    def _append_member_memory(
        session: SessionRecord,
        results: list[AgentTurnResult],
    ) -> None:
        for result in results:
            content = result.content if result.status == ResultStatus.SUCCESS else f"[FAILED] {result.error}"
            memory_entry = f"[{result.stage.value}] {content}"
            session.member_memories.setdefault(result.agent_id, []).append(memory_entry)

    def _build_member_agents(self, config: RoundtableConfig) -> list[MemberAgent]:
        agents: list[MemberAgent] = []
        for member in config.members:
            skills = [
                self.skill_loader.require(skill_reference)
                for skill_reference in member.skill_references
            ]
            agents.append(MemberAgent(role_config=member, client=self.client, skills=skills))
        return agents

    def _build_moderator(self, role_config: RoleConfig) -> ModeratorEngine:
        skills = [
            self.skill_loader.require(skill_reference)
            for skill_reference in role_config.skill_references
        ]
        return ModeratorEngine(role_config=role_config, client=self.client, skills=skills)

    def _build_judge(self, role_config: RoleConfig) -> JudgeEngine:
        skills = [
            self.skill_loader.require(skill_reference)
            for skill_reference in role_config.skill_references
        ]
        return JudgeEngine(role_config=role_config, client=self.client, skills=skills)

    async def _emit_progress(
        self,
        progress_callback: ProgressCallback | None,
        event: DiscussionProgressEvent,
    ) -> None:
        if progress_callback is None:
            return

        callback_result = progress_callback(event)
        if inspect.isawaitable(callback_result):
            await callback_result

    async def _emit_stage_started(
        self,
        progress_callback: ProgressCallback | None,
        session: SessionRecord,
        *,
        stage: DiscussionStage,
        message: str,
    ) -> None:
        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.STAGE_STARTED,
                session_id=session.session_id,
                created_at=utc_now(),
                stage=stage,
                scenario_title=session.scenario.title,
                config_name=session.config_name,
                status=ResultStatus.RUNNING,
                message=message,
            ),
        )

    async def _emit_stage_finished(
        self,
        progress_callback: ProgressCallback | None,
        session: SessionRecord,
        round_result: RoundResult,
    ) -> None:
        success_count = len(
            [result for result in round_result.member_results if result.status == ResultStatus.SUCCESS]
        )
        degraded_count = len(
            [result for result in round_result.member_results if result.status == ResultStatus.DEGRADED]
        )
        error_count = len(
            [result for result in round_result.member_results if result.status == ResultStatus.ERROR]
        )
        if round_result.judge_result and round_result.judge_result.status == ResultStatus.DEGRADED:
            degraded_count += 1
        if round_result.judge_result and round_result.judge_result.status == ResultStatus.ERROR:
            error_count += 1

        await self._emit_progress(
            progress_callback,
            DiscussionProgressEvent(
                event_type=ProgressEventType.STAGE_FINISHED,
                session_id=session.session_id,
                created_at=utc_now(),
                stage=round_result.stage,
                scenario_title=session.scenario.title,
                config_name=session.config_name,
                status=round_result.status,
                message=f"{round_result.stage.value} finished.",
                data={
                    "success_count": success_count,
                    "degraded_count": degraded_count,
                    "error_count": error_count,
                },
            ),
        )

    @staticmethod
    def _derive_round_status(
        member_results: list[AgentTurnResult],
        *,
        judge_result: AgentTurnResult | None = None,
        warnings: list[str] | None = None,
    ) -> ResultStatus:
        has_non_success_member = any(
            result.status != ResultStatus.SUCCESS for result in member_results
        )
        has_non_success_judge = (
            judge_result is not None and judge_result.status != ResultStatus.SUCCESS
        )
        has_warnings = bool([warning for warning in (warnings or []) if warning])

        if has_non_success_member or has_non_success_judge or has_warnings:
            return ResultStatus.DEGRADED
        return ResultStatus.SUCCESS

    @staticmethod
    def _collect_session_warnings(session: SessionRecord) -> list[str]:
        warnings: list[str] = []
        for round_result in session.rounds:
            warnings.extend(round_result.warnings)
        return warnings

    @staticmethod
    def _collect_token_usage(session: SessionRecord) -> TokenUsage:
        total = TokenUsage()
        for round_result in session.rounds:
            for result in round_result.member_results:
                total = total.merged(result.token_usage)
            if round_result.judge_result is not None:
                total = total.merged(round_result.judge_result.token_usage)
        return total

    @staticmethod
    def _determine_session_status(session: SessionRecord) -> SessionStatus:
        if session.error:
            return SessionStatus.FAILED
        if any(round_result.status != ResultStatus.SUCCESS for round_result in session.rounds):
            return SessionStatus.DEGRADED
        return SessionStatus.COMPLETED

    def _persist_session(self, session: SessionRecord) -> None:
        try:
            session.markdown_summary = render_session_markdown(session)
        except Exception as exc:
            session.markdown_summary = (
                f"# Session {session.session_id}\n\n"
                f"Session rendering failed: {exc}\n"
            )
        self.session_store.save(session)
