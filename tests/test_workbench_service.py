from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest

from sandbox.application.workbench_service import WorkbenchService
from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.core.config import AppSettings, ApiSettingsUpdate, load_api_settings, save_api_settings
from sandbox.core.roundtable_config import RoundtableConfigLoader
from sandbox.core.roundtable_engine import RoundtableEngine
from sandbox.schemas.discussion import Scenario, SessionRecord, SessionStatus
from sandbox.skill_loader import SkillLoader
from sandbox.storage.session_store import SessionStore


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


def test_session_store_lists_summaries_and_marks_invalid_files(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)

    session = SessionRecord(
        session_id="session-ok",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Island Control", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# ok",
    )
    store.save(session)

    (tmp_path / "broken.json").write_text("{bad json", encoding="utf-8")

    summaries = store.list_summaries()
    summary_by_id = {summary.session_id: summary for summary in summaries}

    assert summary_by_id["session-ok"].status == "completed"
    assert summary_by_id["session-ok"].title == "Island Control"
    assert summary_by_id["broken"].status == "invalid"
    assert summary_by_id["broken"].error


def test_session_store_uses_persisted_session_status(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)

    degraded_session = SessionRecord(
        session_id="session-degraded",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Degraded", background="Background"),
        status=SessionStatus.DEGRADED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        warnings=["Judge fallback used."],
        markdown_summary="# degraded",
    )
    failed_session = SessionRecord(
        session_id="session-failed",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Failed", background="Background"),
        status=SessionStatus.FAILED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        error="planned failure",
        markdown_summary="# failed",
    )

    store.save(degraded_session)
    store.save(failed_session)

    summaries = store.list_summaries()
    summary_by_id = {summary.session_id: summary for summary in summaries}

    assert summary_by_id["session-degraded"].status == "degraded"
    assert summary_by_id["session-failed"].status == "failed"
    assert summary_by_id["session-failed"].error == "planned failure"


def test_session_store_deletes_session_file(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session = SessionRecord(
        session_id="delete-me",
        config_id="demo",
        config_name="demo.yaml",
        scenario=Scenario(title="Delete Me", background="Background"),
        status=SessionStatus.COMPLETED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        markdown_summary="# delete",
    )

    saved_path = store.save(session)
    store.delete("delete-me")

    assert not saved_path.exists()
    with pytest.raises(FileNotFoundError):
        store.load("delete-me")


def test_session_store_rejects_path_traversal_session_ids(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions")
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError):
        store.load("../outside")
    with pytest.raises(ValueError):
        store.delete("../outside")


def test_roundtable_config_loader_lists_available_configs(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    skills_dir.mkdir()
    configs_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "beta",
                        "display_name": "Analyst Beta",
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

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))
    summaries = loader.list_summaries()

    assert len(summaries) == 1
    assert summaries[0].config_name == "demo.yaml"
    assert summaries[0].member_count == 2
    assert summaries[0].member_names == ["Analyst Alpha", "Analyst Beta"]
    assert summaries[0].generation_max_tokens == 1200
    assert not summaries[0].generation_max_tokens_mixed


def test_roundtable_config_loader_saves_generation_token_limit(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    skills_dir.mkdir()
    configs_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": "alpha.md",
                        "generation": {"temperature": 0.4, "max_tokens": 1000},
                    },
                    {
                        "id": "beta",
                        "display_name": "Analyst Beta",
                        "model": "model-b",
                        "skill": "beta.md",
                        "generation": {"temperature": 0.7, "max_tokens": 2000},
                    },
                ],
                "moderator": {
                    "id": "moderator",
                    "display_name": "Moderator",
                    "model": "moderator-model",
                    "generation": {"temperature": 0.2, "max_tokens": 3000},
                },
                "judge": {
                    "id": "judge",
                    "display_name": "Judge",
                    "model": "judge-model",
                    "generation": {"temperature": 0.1, "max_tokens": 4000},
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))
    before_summary = loader.list_summaries()[0]
    assert before_summary.generation_max_tokens == 4000
    assert before_summary.generation_max_tokens_mixed

    loader.save_generation_max_tokens("demo.yaml", 8192)

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    role_payloads = [*payload["members"], payload["moderator"], payload["judge"]]
    assert [role["generation"]["max_tokens"] for role in role_payloads] == [8192] * 4
    assert loader.load("demo.yaml").members[0].generation.max_tokens == 8192
    after_summary = loader.list_summaries()[0]
    assert after_summary.generation_max_tokens == 8192
    assert not after_summary.generation_max_tokens_mixed


def test_roundtable_config_loader_can_add_member_and_rename_display_name(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    skills_dir.mkdir()
    configs_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "beta",
                        "display_name": "Analyst Beta",
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

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))
    loader.add_member("demo.yaml", display_name="Analyst Gamma", model="model-c")

    config = loader.load("demo.yaml")
    added_member = next(member for member in config.members if member.display_name == "Analyst Gamma")
    assert added_member.id.startswith("member-")
    assert added_member.model == "model-c"
    assert added_member.skill_references == []

    loader.rename_member("demo.yaml", member_id=added_member.id, display_name="Analyst Gamma Prime")

    renamed_config = loader.load("demo.yaml")
    renamed_member = next(member for member in renamed_config.members if member.id == added_member.id)
    assert renamed_member.display_name == "Analyst Gamma Prime"
    assert renamed_member.model == "model-c"


def test_roundtable_config_loader_rejects_duplicate_member_display_names(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    skills_dir.mkdir()
    configs_dir.mkdir()

    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    (configs_dir / "demo.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": "alpha.md",
                    },
                    {
                        "id": "beta",
                        "display_name": "Analyst Beta",
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

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))

    with pytest.raises(ValueError):
        loader.add_member("demo.yaml", display_name="Analyst Alpha", model="model-c")

    with pytest.raises(ValueError):
        loader.rename_member("demo.yaml", member_id="beta", display_name="Analyst Alpha")


def test_roundtable_config_loader_rejects_config_paths_outside_config_dir(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    outside_dir = tmp_path / "outside"
    skills_dir.mkdir()
    configs_dir.mkdir()
    outside_dir.mkdir()
    _write_skill(skills_dir / "alpha.md", "alpha")
    outside_config = outside_dir / "outside.yaml"
    outside_config.write_text(
        yaml.safe_dump(
            {
                "id": "outside",
                "name": "Outside Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": "alpha.md",
                    }
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

    with pytest.raises(ValueError):
        loader.load(str(outside_config))
    with pytest.raises(ValueError):
        loader.save_generation_max_tokens(str(outside_config), 4096)


def test_roundtable_config_loader_rejects_absolute_skill_references_in_config(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    external_skill_dir = tmp_path / "external-skill"
    skills_dir.mkdir()
    configs_dir.mkdir()
    external_skill_dir.mkdir()
    _write_skill(external_skill_dir / "SKILL.md", "external")
    config_path = configs_dir / "demo.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "demo",
                "name": "Demo Config",
                "members": [
                    {
                        "id": "alpha",
                        "display_name": "Analyst Alpha",
                        "model": "model-a",
                        "skill": str(external_skill_dir),
                    }
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

    with pytest.raises(ValueError):
        loader.load("demo.yaml")


def test_api_settings_roundtrip_uses_existing_env_keys(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "AIHUBMIX_BASE_URL=https://api.aihubmix.com/v1\nAIHUBMIX_API_KEY=old-key\n",
        encoding="utf-8",
    )

    save_api_settings(
        ApiSettingsUpdate(
            provider_label="自定义 OpenAI 兼容接口",
            base_url="https://example.com/v1",
            api_key="new-key",
        ),
        env_path=env_path,
    )
    api_settings = load_api_settings(env_path)

    env_text = env_path.read_text(encoding="utf-8")
    assert "AIHUBMIX_BASE_URL='https://example.com/v1'" in env_text
    assert "AIHUBMIX_API_KEY='new-key'" in env_text
    assert api_settings.provider_label == "自定义 OpenAI 兼容接口"
    assert api_settings.base_url == "https://example.com/v1"
    assert api_settings.api_key == "new-key"


def test_workbench_service_runtime_info_masks_api_key_and_updates_client(monkeypatch, tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()
    _write_skill(skills_dir / "alpha.md", "alpha")
    _write_skill(skills_dir / "beta.md", "beta")

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))
    store = SessionStore(sessions_dir)
    settings = AppSettings(
        project_root=tmp_path,
        skills_dir=skills_dir,
        configs_dir=configs_dir,
        sessions_dir=sessions_dir,
        aihubmix_base_url="https://api.aihubmix.com/v1",
        aihubmix_api_key="seed-key",
    )
    ai_client = AIHubMixClient(settings)
    engine = RoundtableEngine(
        config_loader=loader,
        skill_loader=SkillLoader(skills_dir),
        client=ai_client,
        session_store=store,
    )
    service = WorkbenchService(
        settings=settings,
        config_loader=loader,
        session_store=store,
        roundtable_engine=engine,
        ai_client=ai_client,
    )

    monkeypatch.setattr(
        "sandbox.application.workbench_service.load_api_settings",
        lambda: ApiSettingsUpdate(
            provider_label="AIHubMix",
            base_url="https://api.aihubmix.com/v1",
            api_key="seed-key-1234",
        ),
    )

    runtime_info = service.get_runtime_info()
    assert runtime_info["ai_provider_label"] == "AIHubMix"
    assert runtime_info["aihubmix_api_key_masked"].startswith("seed")

    monkeypatch.setattr(
        "sandbox.application.workbench_service.save_api_settings",
        lambda update: AppSettings(
            project_root=tmp_path,
            skills_dir=skills_dir,
            configs_dir=configs_dir,
            sessions_dir=sessions_dir,
            aihubmix_base_url=update.base_url,
            aihubmix_api_key=update.api_key,
        ),
    )
    monkeypatch.setattr(
        "sandbox.application.workbench_service.load_api_settings",
        lambda: ApiSettingsUpdate(
            provider_label="自定义 OpenAI 兼容接口",
            base_url="https://example.com/v1",
            api_key="new-secret-key",
        ),
    )

    updated_runtime = service.save_api_settings(
        provider_label="自定义 OpenAI 兼容接口",
        base_url="https://example.com/v1",
        api_key="new-secret-key",
    )

    assert service.ai_client.base_url == "https://example.com/v1"
    assert service.ai_client.api_key == "new-secret-key"
    assert updated_runtime["aihubmix_base_url"] == "https://example.com/v1"


def test_workbench_service_can_test_multiple_api_connections(monkeypatch, tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    configs_dir = tmp_path / "configs"
    sessions_dir = tmp_path / "sessions"
    skills_dir.mkdir()
    configs_dir.mkdir()
    sessions_dir.mkdir()

    loader = RoundtableConfigLoader(configs_dir, SkillLoader(skills_dir))
    store = SessionStore(sessions_dir)
    settings = AppSettings(
        project_root=tmp_path,
        skills_dir=skills_dir,
        configs_dir=configs_dir,
        sessions_dir=sessions_dir,
    )
    ai_client = AIHubMixClient(settings)
    engine = RoundtableEngine(
        config_loader=loader,
        skill_loader=SkillLoader(skills_dir),
        client=ai_client,
        session_store=store,
    )
    service = WorkbenchService(
        settings=settings,
        config_loader=loader,
        session_store=store,
        roundtable_engine=engine,
        ai_client=ai_client,
    )

    async def fake_probe(connection: dict[str, str]) -> dict[str, str]:
        if connection["name"] == "主接口":
            return {"name": "主接口", "status": "success", "message": "接口可访问。"}
        return {"name": "备用接口", "status": "failed", "message": "HTTP 401"}

    monkeypatch.setattr(WorkbenchService, "_probe_api_connection", staticmethod(fake_probe))

    results = service.test_api_connections(
        [
            {"name": "主接口", "base_url": "https://api.aihubmix.com/v1", "api_key": "key-a"},
            {"name": "备用接口", "base_url": "https://example.com/v1", "api_key": "key-b"},
        ]
    )

    assert results == [
        {"name": "主接口", "status": "success", "message": "接口可访问。"},
        {"name": "备用接口", "status": "failed", "message": "HTTP 401"},
    ]
