from __future__ import annotations

from sandbox.agents.base import BaseChatAgent
from sandbox.schemas.config import MemberConfig
from sandbox.schemas.discussion import AgentTurnResult, CrossQuestionAssignment, Scenario


class ModeratorEngine(BaseChatAgent):
    """The moderator controls pace and defines cross-question targets."""

    async def plan_cross_questions(
        self,
        *,
        scenario: Scenario,
        members: list[MemberConfig],
        stage_one_results: list[AgentTurnResult],
    ) -> tuple[str, list[CrossQuestionAssignment]]:
        assignments = self._build_round_robin_assignments(members, stage_one_results)
        prompt = "\n\n".join(
            [
                "You are the moderator. Give concise guidance for the cross-question stage.",
                scenario.to_prompt_text(),
                self._format_stage_one_results(stage_one_results),
                "Do not reassign targets. Focus only on facilitation and follow-up emphasis.",
                "Return markdown with no more than 8 bullet points.",
            ]
        )
        note = await self.generate(
            prompt=prompt,
            extra_system_instructions=(
                "Your job is to control the table, cut vague talk, "
                "and force members to attack one concrete vulnerability."
            ),
        )
        return note, assignments

    async def build_revision_guidance(
        self,
        *,
        scenario: Scenario,
        stage_two_results: list[AgentTurnResult],
    ) -> str:
        prompt = "\n\n".join(
            [
                "You are the moderator. Give concise revision guidance for the next stage.",
                scenario.to_prompt_text(),
                self._format_stage_two_results(stage_two_results),
                "Return markdown with no more than 8 bullet points.",
            ]
        )
        return await self.generate(
            prompt=prompt,
            extra_system_instructions=(
                "Your job is to force members to answer critiques directly, "
                "not to repeat the first-stage analysis."
            ),
        )

    @staticmethod
    def build_fallback_cross_question_note() -> str:
        return (
            "Please focus on one concrete vulnerability. "
            "Prioritize bad assumptions, ignored constraints, intelligence gaps, and execution risk."
        )

    @staticmethod
    def build_fallback_revision_guidance() -> str:
        return (
            "Please answer the strongest critique directly. "
            "State what you keep, what you revise, and what you drop."
        )

    @staticmethod
    def _build_round_robin_assignments(
        members: list[MemberConfig],
        stage_one_results: list[AgentTurnResult],
    ) -> list[CrossQuestionAssignment]:
        successful_ids = [
            result.agent_id for result in stage_one_results if result.status == "success"
        ]
        member_by_id = {member.id: member for member in members}
        ordered_member_ids = [member.id for member in members]
        assignments: list[CrossQuestionAssignment] = []

        for index, member in enumerate(members):
            target_id = ModeratorEngine._pick_target_id(
                current_member_id=member.id,
                ordered_member_ids=ordered_member_ids,
                successful_ids=successful_ids,
                start_index=index + 1,
            )
            target_member = member_by_id[target_id]
            assignments.append(
                CrossQuestionAssignment(
                    member_id=member.id,
                    member_name=member.display_name,
                    target_member_id=target_member.id,
                    target_member_name=target_member.display_name,
                    reason=(
                        "The moderator uses round-robin assignment and prefers members "
                        "who already produced a reviewable output."
                    ),
                )
            )

        return assignments

    @staticmethod
    def _pick_target_id(
        *,
        current_member_id: str,
        ordered_member_ids: list[str],
        successful_ids: list[str],
        start_index: int,
    ) -> str:
        total_members = len(ordered_member_ids)
        preferred_target_ids = [
            member_id for member_id in ordered_member_ids if member_id in successful_ids
        ]
        search_pool = preferred_target_ids or ordered_member_ids

        for offset in range(total_members):
            ordered_index = (start_index + offset) % total_members
            candidate_id = ordered_member_ids[ordered_index]
            if candidate_id == current_member_id:
                continue
            if candidate_id in search_pool:
                return candidate_id

        return next(member_id for member_id in ordered_member_ids if member_id != current_member_id)

    @staticmethod
    def _format_stage_one_results(results: list[AgentTurnResult]) -> str:
        blocks: list[str] = []
        for result in results:
            content = result.content if result.status == "success" else result.error or "Unknown error"
            blocks.append(f"{result.agent_name}\n{content}")
        return "\n\n".join(blocks)

    @staticmethod
    def _format_stage_two_results(results: list[AgentTurnResult]) -> str:
        blocks: list[str] = []
        for result in results:
            target = result.target_member_name or "Unknown target"
            content = result.content if result.status == "success" else result.error or "Unknown error"
            blocks.append(f"{result.agent_name} questions {target}\n{content}")
        return "\n\n".join(blocks)
