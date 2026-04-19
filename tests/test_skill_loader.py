from __future__ import annotations

from pathlib import Path

from sandbox.skill_loader import SkillLoader


def test_skill_loader_supports_multiple_formats(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    (skills_dir / "alpha.md").write_text(
        """---
id: alpha-skill
name: "Alpha"
core_strategy: "A"
decision_priorities:
  - "P1"
risk_preference: "Low"
information_view: "Info"
tempo_view: "Tempo"
resource_view: "Resource"
common_failure_modes:
  - "F1"
output_format_requirements:
  - "O1"
---

alpha notes
""",
        encoding="utf-8",
    )
    (skills_dir / "beta.yaml").write_text(
        """id: beta-skill
name: "Beta"
core_strategy: "B"
decision_priorities:
  - "P1"
risk_preference: "Medium"
information_view: "Info"
tempo_view: "Tempo"
resource_view: "Resource"
common_failure_modes:
  - "F1"
output_format_requirements:
  - "O1"
""",
        encoding="utf-8",
    )
    (skills_dir / "gamma.json").write_text(
        """{
  "id": "gamma-skill",
  "name": "Gamma",
  "core_strategy": "C",
  "decision_priorities": ["P1"],
  "risk_preference": "High",
  "information_view": "Info",
  "tempo_view": "Tempo",
  "resource_view": "Resource",
  "common_failure_modes": ["F1"],
  "output_format_requirements": ["O1"]
}""",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir)
    skills = loader.load_all()

    assert set(skills) == {"alpha-skill", "beta-skill", "gamma-skill"}
    assert loader.require("alpha-skill").notes == "alpha notes"
    assert loader.require("alpha-skill").category == "未分类"
    assert loader.require("beta.yaml").name == "Beta"
    assert loader.require("beta.yaml").category == "未分类"
    assert loader.require("gamma.json").id == "gamma-skill"


def test_skill_loader_reads_category_when_present(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    (skills_dir / "debate.yaml").write_text(
        """id: debate-skill
name: "Debate"
category: "辩论"
core_strategy: "B"
decision_priorities:
  - "P1"
risk_preference: "Medium"
information_view: "Info"
tempo_view: "Tempo"
resource_view: "Resource"
common_failure_modes:
  - "F1"
output_format_requirements:
  - "O1"
""",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir)
    loader.load_all()

    assert loader.require("debate-skill").category == "辩论"


def test_skill_loader_supports_folder_skill_with_supporting_files(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "debate-kit"
    references_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    references_dir.mkdir(parents=True)
    scripts_dir.mkdir()

    (skill_dir / "SKILL.md").write_text(
        """---
name: "Debate Kit"
description: "Run a structured debate workflow."
category: "辩论"
---

Follow the debate ladder before producing an answer.
""",
        encoding="utf-8",
    )
    (references_dir / "playbook.md").write_text(
        "Use evidence before persuasion.",
        encoding="utf-8",
    )
    (scripts_dir / "check.py").write_text(
        "def check_claim(claim):\n    return claim.strip()\n",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir)
    skills = loader.load_all()
    skill = loader.require("debate-kit")

    assert set(skills) == {"debate-kit"}
    assert skill.name == "Debate Kit"
    assert skill.category == "辩论"
    assert skill.source_file == "debate-kit"
    assert loader.require("debate-kit/SKILL.md") is skill

    prompt_block = skill.to_prompt_block()
    assert "Follow the debate ladder" in prompt_block
    assert "references/playbook.md" in prompt_block
    assert "Use evidence before persuasion." in prompt_block
    assert "scripts/check.py" in prompt_block
    assert "def check_claim" in prompt_block


def test_skill_loader_supports_absolute_folder_skill_reference(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    external_dir = tmp_path / "external-skill"
    references_dir = external_dir / "references"
    skills_dir.mkdir()
    references_dir.mkdir(parents=True)

    (external_dir / "SKILL.md").write_text(
        """---
name: "External Skill"
category: "自定义"
---

Use the selected external folder.
""",
        encoding="utf-8",
    )
    (references_dir / "note.md").write_text(
        "External reference content.",
        encoding="utf-8",
    )

    loader = SkillLoader(skills_dir)
    skill = loader.require(str(external_dir))

    assert skill.id == "external-skill"
    assert skill.name == "External Skill"
    assert skill.source_file == str(external_dir)
    assert "references/note.md" in skill.to_prompt_block()
    assert "External reference content." in skill.to_prompt_block()
