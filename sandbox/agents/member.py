from __future__ import annotations

from sandbox.agents.base import BaseChatAgent
from sandbox.schemas.discussion import AgentTurnResult, CrossQuestionAssignment, Scenario


class MemberAgent(BaseChatAgent):
    """Agent wrapper for one roundtable member."""

    async def independent_judgment(
        self,
        *,
        scenario: Scenario,
        memory_entries: list[str],
    ) -> str:
        prompt = "\n\n".join(
            [
                "请根据下面的沙盘场景独立判断，不要参考其他成员尚未给出的结论。",
                scenario.to_prompt_text(),
                f"你的历史轮次记忆：\n{self.format_memory(memory_entries)}",
                (
                    "请使用 markdown 输出，并严格包含以下二级标题：\n"
                    "## 局势判断\n"
                    "## 敌我优劣\n"
                    "## 首要目标\n"
                    "## 不建议采取的行动"
                ),
            ]
        )
        return await self.generate(
            prompt=prompt,
            extra_system_instructions="你的职责是先独立判断，不要提前迎合其他成员。",
        )

    async def cross_question(
        self,
        *,
        scenario: Scenario,
        assignment: CrossQuestionAssignment,
        target_stage_one_result: AgentTurnResult,
        moderator_note: str,
        memory_entries: list[str],
    ) -> str:
        target_output = self._format_result_for_prompt(target_stage_one_result)
        prompt = "\n\n".join(
            [
                "现在进入交叉质疑阶段，你必须点名指出另一位成员的关键漏洞。",
                scenario.to_prompt_text(),
                f"主持人控场说明：\n{moderator_note}",
                (
                    f"你的质疑对象：{assignment.target_member_name} "
                    f"({assignment.target_member_id})"
                ),
                f"分配原因：{assignment.reason}",
                f"对方第一阶段输出：\n{target_output}",
                f"你的历史轮次记忆：\n{self.format_memory(memory_entries)}",
                (
                    "请使用 markdown 输出，并严格包含以下二级标题：\n"
                    "## 质疑对象\n"
                    "## 我指出的关键漏洞\n"
                    "## 如果忽略该漏洞会怎样\n"
                    "## 我建议对方补充验证什么"
                ),
            ]
        )
        return await self.generate(
            prompt=prompt,
            extra_system_instructions="你的职责是提出尖锐但具体的质疑，必须落到方案漏洞或关键假设上。",
        )

    async def revised_plan(
        self,
        *,
        scenario: Scenario,
        stage_one_result: AgentTurnResult,
        critiques_received: list[AgentTurnResult],
        moderator_note: str,
        memory_entries: list[str],
    ) -> str:
        original_output = self._format_result_for_prompt(stage_one_result)
        critiques_text = self._format_critiques(critiques_received)
        prompt = "\n\n".join(
            [
                "现在进入修正方案阶段，请吸收别人对你的质疑后重新输出方案。",
                scenario.to_prompt_text(),
                f"主持人修正提示：\n{moderator_note}",
                f"你第一阶段的原始输出：\n{original_output}",
                f"其他成员对你的质疑：\n{critiques_text}",
                f"你的历史轮次记忆：\n{self.format_memory(memory_entries)}",
                (
                    "请使用 markdown 输出，并严格包含以下二级标题：\n"
                    "## 我坚持什么\n"
                    "## 我修正什么\n"
                    "## 我放弃什么\n"
                    "## 修正版行动方案"
                ),
            ]
        )
        return await self.generate(
            prompt=prompt,
            extra_system_instructions="你的职责是明确取舍，不要回避自己被质疑的部分。",
        )

    @staticmethod
    def _format_result_for_prompt(result: AgentTurnResult) -> str:
        if result.status == "error":
            return f"[该成员本阶段调用失败]\n{result.error or '未知错误'}"
        return result.content.strip()

    @staticmethod
    def _format_critiques(critiques_received: list[AgentTurnResult]) -> str:
        if not critiques_received:
            return "暂无成员直接点名质疑你，请主动复查自己的关键假设。"

        blocks: list[str] = []
        for critique in critiques_received:
            header = f"{critique.agent_name} -> {critique.target_member_name or '你'}"
            body = critique.content if critique.status == "success" else critique.error or "未知错误"
            blocks.append(f"{header}\n{body}")

        return "\n\n".join(blocks)
