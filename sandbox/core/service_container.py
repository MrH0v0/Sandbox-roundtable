from __future__ import annotations

from dataclasses import dataclass

from sandbox.application.workbench_service import WorkbenchService
from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.core.config import AppSettings, ensure_runtime_directories, load_settings
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import RoundtableEngine
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


@dataclass
class AppServices:
    settings: AppSettings | None
    skill_loader: SkillLoader
    config_loader: RoundtableConfigLoader
    session_store: SessionStore
    ai_client: AIHubMixClient
    roundtable_engine: RoundtableEngine
    workbench_service: WorkbenchService


def build_services() -> AppServices:
    """Build all runtime services once during FastAPI startup."""

    settings = load_settings()
    ensure_runtime_directories(settings)

    skill_loader = SkillLoader(settings.skills_dir)
    skill_loader.load_all()

    config_loader = RoundtableConfigLoader(settings.configs_dir, skill_loader)
    session_store = SessionStore(settings.sessions_dir)
    ai_client = AIHubMixClient(settings)
    roundtable_engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=ai_client,
        session_store=session_store,
    )
    workbench_service = WorkbenchService(
        settings=settings,
        config_loader=config_loader,
        session_store=session_store,
        roundtable_engine=roundtable_engine,
        ai_client=ai_client,
    )

    return AppServices(
        settings=settings,
        skill_loader=skill_loader,
        config_loader=config_loader,
        session_store=session_store,
        ai_client=ai_client,
        roundtable_engine=roundtable_engine,
        workbench_service=workbench_service,
    )
