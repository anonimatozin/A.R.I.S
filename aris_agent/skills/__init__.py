"""Dono: Parte 6 — skills (SKILL.md) e catálogo.

Uso típico (a Parte 8 configura as ferramentas)::

    from aris_agent.skills import SkillLibrary
    from aris_agent.tools.skill_tools import set_library

    set_library(SkillLibrary.from_config(cfg))   # cfg = load_config()

``SkillLibrary`` implementa o protocolo ``SkillCatalog`` do contrato
(``names()``, ``catalog_prompt()``, ``load()``).
"""

from __future__ import annotations

from .frontmatter import FrontmatterError, parse_frontmatter, validar_campos
from .library import SkillEntry, SkillError, SkillLibrary, project_skills_dir

__all__ = [
    "FrontmatterError",
    "SkillEntry",
    "SkillError",
    "SkillLibrary",
    "parse_frontmatter",
    "project_skills_dir",
    "validar_campos",
]
