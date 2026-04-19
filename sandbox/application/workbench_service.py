from __future__ import annotations

import asyncio

import httpx

from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.core.config import ApiSettingsUpdate, AppSettings, load_api_settings, save_api_settings
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import ProgressCallback, RoundtableEngine
from sandbox.schemas.config import RoundtableConfigSummary
from sandbox.schemas.discussion import (
    MemberRuntimeOverride,
    RunDiscussionResponse,
    Scenario,
    SessionSummary,
)
from sandbox.storage.session_store import SessionStore


class WorkbenchService:
    """Shared application entrypoint for API routes and desktop UI."""

    def __init__(
        self,
        *,
        settings: AppSettings | None,
        config_loader: RoundtableConfigLoader,
        session_store: SessionStore,
        roundtable_engine: RoundtableEngine,
        ai_client: AIHubMixClient,
    ) -> None:
        self.settings = settings
        self.config_loader = config_loader
        self.session_store = session_store
        self.roundtable_engine = roundtable_engine
        self.ai_client = ai_client

    async def run_discussion(
        self,
        *,
        scenario: Scenario,
        config_name: str,
        member_overrides: list[MemberRuntimeOverride] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> RunDiscussionResponse:
        session = await self.roundtable_engine.run_full_discussion(
            scenario=scenario,
            config_name=config_name,
            member_overrides=member_overrides,
            progress_callback=progress_callback,
        )
        return RunDiscussionResponse(
            session_id=session.session_id,
            session=session,
            markdown=session.markdown_summary,
        )

    def load_session(self, session_id: str) -> RunDiscussionResponse:
        session = self.session_store.load(session_id)
        return RunDiscussionResponse(
            session_id=session.session_id,
            session=session,
            markdown=session.markdown_summary,
        )

    def delete_session(self, session_id: str) -> None:
        self.session_store.delete(session_id)

    def list_sessions(self, *, limit: int | None = None) -> list[SessionSummary]:
        return self.session_store.list_summaries(limit=limit)

    def list_configs(self) -> list[RoundtableConfigSummary]:
        return self.config_loader.list_summaries()

    def get_runtime_info(self) -> dict[str, str]:
        api_settings = load_api_settings()
        runtime_info = {
            "ai_provider_label": api_settings.provider_label,
            "aihubmix_base_url": api_settings.base_url,
            "aihubmix_api_key": api_settings.api_key,
            "aihubmix_api_key_masked": self._mask_api_key(api_settings.api_key),
            "api_requires_restart": "true",
        }
        if self.settings is None:
            return runtime_info

        runtime_info.update(
            {
                "project_root": str(self.settings.project_root),
                "skills_dir": str(self.settings.skills_dir),
                "configs_dir": str(self.settings.configs_dir),
                "sessions_dir": str(self.settings.sessions_dir),
                "aihubmix_base_url": self.settings.aihubmix_base_url,
            }
        )
        return runtime_info

    def get_api_settings(self) -> ApiSettingsUpdate:
        return load_api_settings()

    def save_api_settings(
        self,
        *,
        provider_label: str,
        base_url: str,
        api_key: str,
    ) -> dict[str, str]:
        persisted_settings = save_api_settings(
            ApiSettingsUpdate(
                provider_label=provider_label,
                base_url=base_url,
                api_key=api_key,
            )
        )
        self.settings = persisted_settings
        self.ai_client.base_url = persisted_settings.aihubmix_base_url
        self.ai_client.api_key = persisted_settings.aihubmix_api_key
        return self.get_runtime_info()

    def save_config_token_limit(self, *, config_name: str, max_tokens: int) -> None:
        self.config_loader.save_generation_max_tokens(config_name, max_tokens)

    def add_config_member(self, *, config_name: str, display_name: str, model: str) -> None:
        self.config_loader.add_member(
            config_name,
            display_name=display_name,
            model=model,
        )

    def rename_config_member(self, *, config_name: str, member_id: str, display_name: str) -> None:
        self.config_loader.rename_member(
            config_name,
            member_id=member_id,
            display_name=display_name,
        )

    def test_api_connections(self, connections: list[dict[str, str]]) -> list[dict[str, str]]:
        async def run_batch() -> list[dict[str, str]]:
            results: list[dict[str, str]] = []
            for connection in connections:
                results.append(await self._probe_api_connection(connection))
            return results

        return asyncio.run(run_batch())

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        cleaned = api_key.strip()
        if not cleaned:
            return "未设置"
        if len(cleaned) <= 8:
            return "*" * len(cleaned)
        return f"{cleaned[:4]}{'*' * (len(cleaned) - 8)}{cleaned[-4:]}"

    @staticmethod
    async def _probe_api_connection(connection: dict[str, str]) -> dict[str, str]:
        name = str(connection.get("name") or "未命名 API").strip()
        base_url = str(connection.get("base_url") or "").strip().rstrip("/")
        api_key = str(connection.get("api_key") or "").strip()

        if not base_url:
            return {"name": name, "status": "failed", "message": "缺少 Base URL。"}
        if not api_key:
            return {"name": name, "status": "failed", "message": "缺少 API Key。"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
                response = await client.get(f"{base_url}/models", headers=headers)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "name": name,
                "status": "failed",
                "message": f"HTTP {exc.response.status_code}",
            }
        except Exception as exc:
            return {
                "name": name,
                "status": "failed",
                "message": str(exc),
            }

        return {
            "name": name,
            "status": "success",
            "message": "接口可访问。",
        }

    async def aclose(self) -> None:
        await self.ai_client.aclose()
