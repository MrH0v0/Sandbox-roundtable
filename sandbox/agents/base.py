from __future__ import annotations

from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.schemas.config import RoleConfig
from sandbox.schemas.skill import SkillDefinition
from sandbox.schemas.usage import ChatCompletionResult, TokenUsage


class BaseChatAgent:
    """Shared helper for any role that talks to the LLM API."""

    def __init__(
        self,
        *,
        role_config: RoleConfig,
        client: AIHubMixClient,
        skill: SkillDefinition | None = None,
        skills: list[SkillDefinition] | None = None,
    ):
        self.role_config = role_config
        self.client = client
        self.skills = list(skills or [])
        if skill is not None and skill.id not in {item.id for item in self.skills}:
            self.skills.insert(0, skill)
        self.skill = self.skills[0] if self.skills else None
        self.last_token_usage: TokenUsage | None = None

    @property
    def skill_id(self) -> str | None:
        return self.skill.id if self.skill else None

    @property
    def skill_ids(self) -> list[str]:
        return [skill.id for skill in self.skills]

    async def generate(self, *, prompt: str, extra_system_instructions: str) -> str:
        self.last_token_usage = None
        system_prompt = self._build_system_prompt(extra_system_instructions)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        result = await self.client.chat_completion(
            model=self.role_config.model,
            messages=messages,
            generation=self.role_config.generation,
        )
        if isinstance(result, ChatCompletionResult):
            self.last_token_usage = result.usage
            return result.content
        return str(result)

    def _build_system_prompt(self, extra_system_instructions: str) -> str:
        skill_block = self._build_skill_block()

        return "\n\n".join(
            [
                f"你是圆桌讨论引擎中的角色：{self.role_config.display_name}。",
                "模型身份与 skill 文件必须分离。不要把自己描述成某个固定历史人物。",
                extra_system_instructions.strip(),
                f"外部 skill 内容如下：\n{skill_block}",
                "输出请保持清晰、克制、可审阅，避免空泛套话。",
            ]
        )

    def _build_skill_block(self) -> str:
        if not self.skills:
            return "未绑定外部 skill 文件。请仅依据角色职责执行，不要虚构额外设定。"
        return "\n\n---\n\n".join(skill.to_prompt_block() for skill in self.skills)

    @staticmethod
    def format_memory(memory_entries: list[str]) -> str:
        if not memory_entries:
            return "暂无历史轮次记忆。"
        return "\n\n".join(memory_entries)
