from __future__ import annotations

from sandbox.agents.base import BaseChatAgent
from sandbox.schemas.discussion import AgentTurnResult, Scenario


class JudgeEngine(BaseChatAgent):
    """The judge summarizes consensus, disagreements and action advice."""

    async def render_final_verdict(
        self,
        *,
        scenario: Scenario,
        stage_one_results: list[AgentTurnResult],
        stage_two_results: list[AgentTurnResult],
        stage_three_results: list[AgentTurnResult],
        moderator_notes: list[str],
    ) -> str:
        prompt = "\n\n".join(
            [
                "You are the judge. Produce the final verdict from the full discussion.",
                scenario.to_prompt_text(),
                f"Stage 1 summary:\n{self._format_results(stage_one_results)}",
                f"Stage 2 summary:\n{self._format_results(stage_two_results)}",
                f"Stage 3 summary:\n{self._format_results(stage_three_results)}",
                "Moderator notes:",
                "\n\n".join(note.strip() for note in moderator_notes if note.strip()) or "None",
                (
                    "Return markdown and include exactly these headings:\n"
                    "## Consensus\n"
                    "## Main Disagreements\n"
                    "## Largest Risk\n"
                    "## Recommended Action\n"
                    "## Intelligence Needed Next"
                ),
            ]
        )
        return await self.generate(
            prompt=prompt,
            extra_system_instructions=(
                "Your job is to produce a final ruling with a concrete recommendation and risk statement."
            ),
        )

    @staticmethod
    def build_fallback_verdict(
        stage_one_results: list[AgentTurnResult],
        stage_two_results: list[AgentTurnResult],
        stage_three_results: list[AgentTurnResult],
    ) -> str:
        successful_members = [
            result.agent_name for result in stage_three_results if result.status == "success"
        ]
        failed_members = [
            result.agent_name for result in stage_three_results if result.status == "error"
        ]
        question_count = sum(1 for result in stage_two_results if result.status == "success")
        stage_one_success_count = sum(
            1 for result in stage_one_results if result.status == "success"
        )

        consensus = (
            f"- {stage_one_success_count} members completed the independent judgment stage.\n"
            f"- Members with a successful revised plan: {', '.join(successful_members) or 'None'}."
        )
        disagreements = (
            "- The judge model failed, so detailed disagreement analysis must be reviewed from the raw outputs."
        )
        risks = (
            "- The largest risk is incomplete consensus because some member outputs are missing."
            if failed_members
            else "- The largest risk still requires manual review of the revised plans."
        )
        action = "- Compare the successful revised plans manually before making a final decision."
        intelligence = (
            f"- Failed members to recover next round: {', '.join(failed_members) or 'None'}.\n"
            f"- Effective cross-questions already raised this round: {question_count}."
        )

        return "\n\n".join(
            [
                "## Consensus",
                consensus,
                "## Main Disagreements",
                disagreements,
                "## Largest Risk",
                risks,
                "## Recommended Action",
                action,
                "## Intelligence Needed Next",
                intelligence,
            ]
        )

    @staticmethod
    def _format_results(results: list[AgentTurnResult]) -> str:
        blocks: list[str] = []
        for result in results:
            header = result.agent_name
            if result.target_member_name:
                header = f"{result.agent_name} -> {result.target_member_name}"
            content = result.content if result.status == "success" else result.error or "Unknown error"
            blocks.append(f"{header}\n{content}")
        return "\n\n".join(blocks)
