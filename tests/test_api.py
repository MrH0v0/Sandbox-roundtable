from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from sandbox.application.workbench_service import WorkbenchService
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import RoundtableEngine
from sandbox.core.service_container import AppServices
from sandbox.main import create_app
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


class FakeAIClient:
    def __init__(self, *, fail_models: set[str] | None = None) -> None:
        self.fail_models = fail_models or set()

    async def chat_completion(self, *, model: str, messages, generation) -> str:
        await asyncio.sleep(0.001)
        if model in self.fail_models:
            raise RuntimeError("planned api failure")
        return f"{model} response"

    async def aclose(self) -> None:
        return None


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


def test_api_can_run_and_replay_session(tmp_path: Path) -> None:
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
    workbench_service = WorkbenchService(
        settings=None,
        config_loader=config_loader,
        session_store=session_store,
        roundtable_engine=engine,
        ai_client=fake_client,
    )
    services = AppServices(
        settings=None,
        skill_loader=skill_loader,
        config_loader=config_loader,
        session_store=session_store,
        ai_client=fake_client,
        roundtable_engine=engine,
        workbench_service=workbench_service,
    )
    app = create_app(lambda: services)

    with TestClient(app) as client:
        run_response = client.post(
            "/api/v1/discussions/run",
            json={
                "config_name": "demo.yaml",
                "scenario": {
                    "title": "Scenario",
                    "background": "Background",
                    "constraints": ["Constraint"],
                    "friendly_forces": ["Friendly"],
                    "enemy_forces": ["Enemy"],
                    "objectives": ["Objective"],
                    "victory_conditions": ["Victory"],
                },
            },
        )

        assert run_response.status_code == 200
        assert run_response.json()["session"]["status"] == "completed"
        session_id = run_response.json()["session_id"]

        replay_response = client.get(f"/api/v1/sessions/{session_id}")
        assert replay_response.status_code == 200
        assert replay_response.json()["session_id"] == session_id
        assert replay_response.json()["session"]["status"] == "completed"


def test_api_returns_degraded_session_when_judge_falls_back(tmp_path: Path) -> None:
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
    fake_client = FakeAIClient(fail_models={"judge-model"})
    engine = RoundtableEngine(
        config_loader=config_loader,
        skill_loader=skill_loader,
        client=fake_client,
        session_store=session_store,
    )
    workbench_service = WorkbenchService(
        settings=None,
        config_loader=config_loader,
        session_store=session_store,
        roundtable_engine=engine,
        ai_client=fake_client,
    )
    services = AppServices(
        settings=None,
        skill_loader=skill_loader,
        config_loader=config_loader,
        session_store=session_store,
        ai_client=fake_client,
        roundtable_engine=engine,
        workbench_service=workbench_service,
    )
    app = create_app(lambda: services)

    with TestClient(app) as client:
        run_response = client.post(
            "/api/v1/discussions/run",
            json={
                "config_name": "demo.yaml",
                "scenario": {
                    "title": "Scenario",
                    "background": "Background",
                    "constraints": ["Constraint"],
                    "friendly_forces": ["Friendly"],
                    "enemy_forces": ["Enemy"],
                    "objectives": ["Objective"],
                    "victory_conditions": ["Victory"],
                },
            },
        )

        assert run_response.status_code == 200
        payload = run_response.json()
        assert payload["session"]["status"] == "degraded"
        assert payload["session"]["rounds"][-1]["judge_result"]["status"] == "degraded"
