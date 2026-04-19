from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from sandbox.schemas.skill import SkillDefinition


MARKDOWN_FRONT_MATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n(.*))?$",
    re.DOTALL,
)


class SkillError(ValueError):
    """Base class for all skill loading errors."""


class SkillNotFoundError(SkillError):
    """Raised when a role references a missing skill."""


class SkillFormatError(SkillError):
    """Raised when a skill file exists but is malformed."""


class SkillLoader:
    """Central place for scanning, parsing and validating external skills."""

    SUPPORTED_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".json"}
    FOLDER_SKILL_FILENAME = "SKILL.md"
    SUPPORTING_DIR_NAMES = ("references", "scripts")
    SUPPORTING_SUFFIXES = {
        ".md",
        ".markdown",
        ".txt",
        ".py",
        ".js",
        ".ts",
        ".json",
        ".yaml",
        ".yml",
    }
    MAX_SUPPORTING_FILE_CHARS = 12_000
    MAX_SUPPORTING_TOTAL_CHARS = 30_000

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._skills_by_id: dict[str, SkillDefinition] = {}
        self._skills_by_filename: dict[str, SkillDefinition] = {}

    def load_all(self) -> dict[str, SkillDefinition]:
        if not self.skills_dir.exists():
            raise SkillError(f"Skills directory does not exist: {self.skills_dir}")

        skills_by_id: dict[str, SkillDefinition] = {}
        skills_by_filename: dict[str, SkillDefinition] = {}

        for path in sorted(self.skills_dir.iterdir()):
            skill_path = self._resolve_skill_path(path)
            if skill_path is None:
                continue

            source_file = path.name if path.is_dir() else path.name
            default_id = path.name if path.is_dir() else path.stem
            supporting_root = path if path.is_dir() else None
            skill = self._parse_skill_file(
                skill_path,
                source_file=source_file,
                default_id=default_id,
                supporting_root=supporting_root,
            )
            if skill.id in skills_by_id:
                raise SkillFormatError(
                    f"Duplicate skill id '{skill.id}' found in {path.name}."
                )

            skills_by_id[skill.id] = skill
            for reference in self._reference_keys(path, skill):
                if reference in skills_by_filename:
                    raise SkillFormatError(
                        f"Duplicate skill reference '{reference}' found in {path.name}."
                    )
                skills_by_filename[reference] = skill

        self._skills_by_id = skills_by_id
        self._skills_by_filename = skills_by_filename
        return skills_by_id

    def get(self, reference: str | None) -> SkillDefinition | None:
        if reference is None:
            return None

        if not self._skills_by_id and not self._skills_by_filename:
            self.load_all()

        return (
            self._skills_by_id.get(reference)
            or self._skills_by_filename.get(reference)
            or self._load_external_folder_skill(reference)
        )

    def require(self, reference: str) -> SkillDefinition:
        skill = self.get(reference)
        if skill is None:
            raise SkillNotFoundError(
                f"Skill '{reference}' was not found in {self.skills_dir}."
            )
        return skill

    def _resolve_skill_path(self, path: Path) -> Path | None:
        if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES:
            return path

        if path.is_dir():
            skill_path = path / self.FOLDER_SKILL_FILENAME
            if skill_path.is_file():
                return skill_path

        return None

    def _parse_skill_file(
        self,
        path: Path,
        *,
        source_file: str | None = None,
        default_id: str | None = None,
        supporting_root: Path | None = None,
    ) -> SkillDefinition:
        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"Failed to read skill file {path}: {exc}") from exc

        body_notes: str | None = None
        suffix = path.suffix.lower()

        if suffix in {".yaml", ".yml"}:
            payload = yaml.safe_load(raw_text) or {}
        elif suffix == ".json":
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise SkillFormatError(f"Invalid JSON skill file {path.name}: {exc}") from exc
        else:
            payload, body_notes = self._parse_markdown_front_matter(path.name, raw_text)

        if not isinstance(payload, dict):
            raise SkillFormatError(f"Skill file {path.name} must contain a top-level object.")

        normalized_payload = dict(payload)
        normalized_payload.setdefault("id", default_id or path.stem)
        normalized_payload.setdefault("name", normalized_payload["id"])
        normalized_payload["source_file"] = source_file or path.name
        self._apply_generic_skill_defaults(normalized_payload, body_notes)

        if body_notes and not normalized_payload.get("notes"):
            normalized_payload["notes"] = body_notes.strip()

        supporting_files = self._load_supporting_files(supporting_root)
        if supporting_files:
            normalized_payload["supporting_files"] = supporting_files

        try:
            return SkillDefinition.model_validate(normalized_payload)
        except ValidationError as exc:
            raise SkillFormatError(f"Invalid skill file {path.name}: {exc}") from exc

    def _reference_keys(self, path: Path, skill: SkillDefinition) -> list[str]:
        keys = [skill.source_file]
        if path.is_dir():
            keys.append(f"{path.name}/{self.FOLDER_SKILL_FILENAME}")
        return keys

    def _load_external_folder_skill(self, reference: str) -> SkillDefinition | None:
        path = Path(reference)
        if not path.is_absolute() or not path.is_dir():
            return None

        skill_path = path / self.FOLDER_SKILL_FILENAME
        if not skill_path.is_file():
            return None

        skill = self._parse_skill_file(
            skill_path,
            source_file=str(path),
            default_id=path.name,
            supporting_root=path,
        )
        self._skills_by_id.setdefault(skill.id, skill)
        self._skills_by_filename[str(path)] = skill
        return skill

    @staticmethod
    def _apply_generic_skill_defaults(payload: dict, body_notes: str | None) -> None:
        notes = (body_notes or "").strip()
        description = str(payload.get("description") or "").strip()
        fallback = description or notes or str(payload.get("name") or payload.get("id") or "").strip()

        payload.setdefault("core_strategy", fallback)
        payload.setdefault("decision_priorities", ["Follow the SKILL.md workflow and constraints."])
        payload.setdefault("risk_preference", "Follow the SKILL.md risk guidance.")
        payload.setdefault("information_view", "Use the bundled skill instructions and references.")
        payload.setdefault("tempo_view", "Follow the requested task pace.")
        payload.setdefault("resource_view", "Use the skill folder context when relevant.")
        payload.setdefault("common_failure_modes", ["Ignoring bundled skill instructions."])
        payload.setdefault("output_format_requirements", ["Match the current task output requirements."])

    def _load_supporting_files(self, root: Path | None) -> list[dict[str, object]]:
        if root is None:
            return []

        files: list[dict[str, object]] = []
        remaining = self.MAX_SUPPORTING_TOTAL_CHARS
        for dirname in self.SUPPORTING_DIR_NAMES:
            folder = root / dirname
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if remaining <= 0:
                    return files
                if not path.is_file() or path.suffix.lower() not in self.SUPPORTING_SUFFIXES:
                    continue

                try:
                    content = path.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    continue
                if not content:
                    continue

                truncated = False
                if len(content) > self.MAX_SUPPORTING_FILE_CHARS:
                    content = content[: self.MAX_SUPPORTING_FILE_CHARS].rstrip()
                    truncated = True
                if len(content) > remaining:
                    content = content[:remaining].rstrip()
                    truncated = True

                relative_path = path.relative_to(root).as_posix()
                files.append(
                    {
                        "path": relative_path,
                        "content": content,
                        "truncated": truncated,
                    }
                )
                remaining -= len(content)
        return files

    @staticmethod
    def _parse_markdown_front_matter(filename: str, text: str) -> tuple[dict, str | None]:
        match = MARKDOWN_FRONT_MATTER.match(text)
        if not match:
            raise SkillFormatError(
                f"Markdown skill '{filename}' must start with YAML front matter."
            )

        front_matter_text = match.group(1)
        notes = match.group(2)

        try:
            payload = yaml.safe_load(front_matter_text) or {}
        except yaml.YAMLError as exc:
            raise SkillFormatError(
                f"Invalid markdown front matter in '{filename}': {exc}"
            ) from exc

        return payload, notes
