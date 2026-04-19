from __future__ import annotations

import json
from pathlib import Path

import yaml

from sandbox.schemas.config import (
    MemberConfigSummary,
    RoundtableConfig,
    RoundtableConfigSummary,
    RoleConfig,
    SkillCatalogItem,
)
from sandbox.skill_loader import SkillLoader


class RoundtableConfigLoader:
    """Load and validate roundtable member configuration files."""

    SUPPORTED_SUFFIXES = (".yaml", ".yml", ".json")

    def __init__(self, configs_dir: Path, skill_loader: SkillLoader):
        self.configs_dir = configs_dir.resolve()
        self.skill_loader = skill_loader

    def load(self, config_name: str) -> RoundtableConfig:
        self.skill_loader.load_all()
        config_path = self._resolve_config_path(config_name)
        payload = self._read_config_payload(config_path)
        config = RoundtableConfig.model_validate(payload)
        self._validate_skill_references(config)
        return config

    def list_summaries(self) -> list[RoundtableConfigSummary]:
        self.skill_loader.load_all()
        summaries: list[RoundtableConfigSummary] = []
        for path in sorted(self.configs_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
                continue

            try:
                payload = self._read_config_payload(path)
                config = RoundtableConfig.model_validate(payload)
                self._validate_skill_references(config)
            except Exception:
                continue

            token_limits = self._generation_max_tokens(config)

            summaries.append(
                RoundtableConfigSummary(
                    config_name=path.name,
                    id=config.id,
                    name=config.name,
                    member_count=len(config.members),
                    member_names=[member.display_name for member in config.members],
                    moderator_name=config.moderator.display_name,
                    judge_name=config.judge.display_name,
                    members=[
                        MemberConfigSummary(
                            id=member.id,
                            display_name=member.display_name,
                            model=member.model,
                            skills=member.skill_references,
                        )
                        for member in config.members
                    ],
                    available_models=self._available_models(config),
                    skills=self._skill_catalog(),
                    generation_max_tokens=max(token_limits),
                    generation_max_tokens_mixed=len(set(token_limits)) > 1,
                )
            )

        return summaries

    def save_generation_max_tokens(self, config_name: str, max_tokens: int) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than 0.")

        config_path = self._resolve_config_path(config_name)
        payload = self._read_config_payload(config_path)
        role_payloads = [
            *(payload.get("members") or []),
            payload.get("moderator", {}),
            payload.get("judge", {}),
        ]
        for role_payload in role_payloads:
            if not isinstance(role_payload, dict):
                continue
            generation = role_payload.setdefault("generation", {})
            if not isinstance(generation, dict):
                generation = {}
                role_payload["generation"] = generation
            generation["max_tokens"] = max_tokens

        config = RoundtableConfig.model_validate(payload)
        self._validate_skill_references(config)
        self._write_config_payload(config_path, payload)

    def add_member(self, config_name: str, *, display_name: str, model: str) -> None:
        cleaned_name = str(display_name or "").strip()
        cleaned_model = str(model or "").strip()
        if not cleaned_name:
            raise ValueError("Member display name cannot be empty.")
        if not cleaned_model:
            raise ValueError("Member model cannot be empty.")

        config_path = self._resolve_config_path(config_name)
        payload = self._read_config_payload(config_path)
        config = RoundtableConfig.model_validate(payload)
        self._validate_skill_references(config)
        self._ensure_unique_member_display_name(config, cleaned_name)

        members_payload = payload.setdefault("members", [])
        if not isinstance(members_payload, list):
            raise ValueError("Config members payload must be a list.")

        members_payload.append(
            {
                "id": self._next_member_id(config),
                "display_name": cleaned_name,
                "model": cleaned_model,
                "skills": [],
            }
        )

        updated_config = RoundtableConfig.model_validate(payload)
        self._validate_skill_references(updated_config)
        self._write_config_payload(config_path, payload)

    def rename_member(self, config_name: str, *, member_id: str, display_name: str) -> None:
        cleaned_member_id = str(member_id or "").strip()
        cleaned_name = str(display_name or "").strip()
        if not cleaned_member_id:
            raise ValueError("Member id cannot be empty.")
        if not cleaned_name:
            raise ValueError("Member display name cannot be empty.")

        config_path = self._resolve_config_path(config_name)
        payload = self._read_config_payload(config_path)
        config = RoundtableConfig.model_validate(payload)
        self._validate_skill_references(config)
        self._ensure_unique_member_display_name(config, cleaned_name, exclude_member_id=cleaned_member_id)

        members_payload = payload.get("members")
        if not isinstance(members_payload, list):
            raise ValueError("Config members payload must be a list.")

        for member_payload in members_payload:
            if not isinstance(member_payload, dict):
                continue
            if str(member_payload.get("id") or "").strip() != cleaned_member_id:
                continue
            member_payload["display_name"] = cleaned_name
            updated_config = RoundtableConfig.model_validate(payload)
            self._validate_skill_references(updated_config)
            self._write_config_payload(config_path, payload)
            return

        raise ValueError(f"Unknown member id: {cleaned_member_id}")

    def _resolve_config_path(self, config_name: str) -> Path:
        config_text = str(config_name or "").strip()
        if not config_text:
            raise FileNotFoundError("Config file name is empty.")

        candidate = Path(config_text)
        candidates: list[Path] = []
        if candidate.suffix.lower() in self.SUPPORTED_SUFFIXES:
            candidates.append(candidate)
        elif not candidate.suffix:
            candidates.extend(Path(f"{config_text}{suffix}") for suffix in self.SUPPORTED_SUFFIXES)
        else:
            raise FileNotFoundError(f"Unsupported config file suffix: {candidate.suffix}")

        for current_candidate in candidates:
            path = current_candidate if current_candidate.is_absolute() else self.configs_dir / current_candidate
            resolved = path.resolve()
            if not self._is_relative_to(resolved, self.configs_dir):
                raise ValueError("Config path resolves outside the configs directory.")
            if resolved.exists() and resolved.is_file():
                return resolved

        raise FileNotFoundError(
            f"Config file '{config_text}' was not found in {self.configs_dir}."
        )

    @staticmethod
    def _read_config_payload(path: Path) -> dict:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml.safe_load(text) or {}

    @staticmethod
    def _write_config_payload(path: Path, payload: dict) -> None:
        if path.suffix.lower() == ".json":
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _validate_skill_references(self, config: RoundtableConfig) -> None:
        for member in config.members:
            for skill_reference in member.skill_references:
                self._validate_config_skill_reference(skill_reference)
                self.skill_loader.require(skill_reference)

        for role in (config.moderator, config.judge):
            self._validate_optional_role_skill(role)

    def _validate_optional_role_skill(self, role: RoleConfig) -> None:
        for skill_reference in role.skill_references:
            self._validate_config_skill_reference(skill_reference)
            self.skill_loader.require(skill_reference)

    @staticmethod
    def _validate_config_skill_reference(skill_reference: str) -> None:
        if Path(str(skill_reference)).is_absolute():
            raise ValueError("Config files cannot reference absolute skill folders.")

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _available_models(config: RoundtableConfig) -> list[str]:
        models = {member.model for member in config.members}
        models.add(config.moderator.model)
        models.add(config.judge.model)
        return sorted(model for model in models if model)

    @staticmethod
    def _generation_max_tokens(config: RoundtableConfig) -> list[int]:
        roles = [*config.members, config.moderator, config.judge]
        return [role.generation.max_tokens for role in roles]

    def _skill_catalog(self) -> list[SkillCatalogItem]:
        skills = self.skill_loader.load_all().values()
        return [
            SkillCatalogItem(
                id=skill.id,
                name=skill.name,
                category=skill.category,
                source_file=skill.source_file,
            )
            for skill in sorted(skills, key=lambda item: (item.category, item.name, item.id))
        ]

    @staticmethod
    def _ensure_unique_member_display_name(
        config: RoundtableConfig,
        display_name: str,
        *,
        exclude_member_id: str | None = None,
    ) -> None:
        duplicate_names = {
            member.display_name
            for member in config.members
            if member.id != exclude_member_id and member.display_name == display_name
        }
        if duplicate_names:
            raise ValueError(f"Duplicate member display name: {display_name}")

    @staticmethod
    def _next_member_id(config: RoundtableConfig) -> str:
        existing_ids = {member.id for member in config.members}
        existing_ids.add(config.moderator.id)
        existing_ids.add(config.judge.id)
        next_index = 1
        while True:
            candidate = f"member-{next_index}"
            if candidate not in existing_ids:
                return candidate
            next_index += 1
