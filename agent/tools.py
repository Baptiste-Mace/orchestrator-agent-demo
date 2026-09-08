"""Boîte à outils de l'agent : rassemble les skills locales et les outils MCP,
et décide (via le LLM) si l'un d'eux aide pour l'étape courante.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import SKILLS_DIR, load_prompt
from .llm import LLMProvider, Message
from .mcp_client import MCPManager
from .util import ask_json, wants_narration


@dataclass
class Skill:
    name: str
    description: str
    prompt_file: str

    def guidance(self) -> str:
        return (SKILLS_DIR / self.prompt_file).read_text(encoding="utf-8")


@dataclass
class ToolChoice:
    kind: str                 # "none" | "skill" | "mcp"
    name: Optional[str]
    result: str = ""          # sortie d'un outil MCP, ou guidance d'une skill
    label: str = "none"       # trace lisible : "skill:x" / "mcp:srv/outil"


def load_skills() -> List[Skill]:
    path = SKILLS_DIR / "skills.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Skill(**s) for s in data.get("skills", [])]


class Toolbox:
    """Vue unifiée des capacités + logique de sélection avant exécution."""

    def __init__(self, skills: List[Skill], mcp: MCPManager, llm: LLMProvider):
        self.skills = skills
        self.mcp = mcp
        self.llm = llm
        self._selection_prompt = load_prompt("tool_selection")
        self._between_prompt = load_prompt("between_steps")

    def find_mcp_tool(self, suffix: str) -> Optional[str]:
        """Retourne le nom qualifié d'un outil MCP dont le nom finit par `suffix`
        (ex: '/say'), sans coder en dur le nom du serveur. None si absent."""
        for item in self.mcp.catalog():
            if item["name"].endswith(suffix):
                return item["name"]
        return None

    def catalog(self) -> List[dict]:
        """Catalogue complet présenté au sélecteur (skills + outils MCP)."""
        items = [{"type": "skill", "name": s.name, "description": s.description,
                  "schema": {}} for s in self.skills]
        items.extend(self.mcp.catalog())
        return items

    def select_for(self, step: str, context: str = ""):
        """Demande au LLM si une capacité aide pour `step`.

        `context` = contexte enrichi (résultats précédents, fichiers) : il permet
        au sélecteur de construire des ARGUMENTS corrects pour un outil MCP
        (ex: le vrai texte à copier, généré à une étape antérieure).

        Retourne (ToolChoice, tokens_consommés). Exécute l'outil MCP si choisi.
        """
        catalog = self.catalog()
        if not catalog:
            return ToolChoice(kind="none", name=None), 0

        catalog_text = json.dumps(catalog, ensure_ascii=False, indent=2)
        user = ""
        if context:
            user += f"CONTEXTE:\n{context}\n\n"
        user += f"ÉTAPE:\n{step}\n\nCATALOGUE:\n{catalog_text}"
        messages = [
            Message("system", self._selection_prompt),
            Message("user", user),
        ]
        decision, tokens = ask_json(self.llm, messages)
        use = decision.get("use", "none")

        if use == "skill":
            skill = next((s for s in self.skills if s.name == decision.get("name")), None)
            if skill:
                return (ToolChoice(kind="skill", name=skill.name,
                                   result=skill.guidance(),
                                   label=f"skill:{skill.name}"),
                        tokens)

        if use == "mcp":
            name = decision.get("name")
            try:
                output = self.mcp.call(name, decision.get("arguments", {}))
                return (ToolChoice(kind="mcp", name=name, result=output,
                                   label=f"mcp:{name}"),
                        tokens)
            except Exception as e:
                return (ToolChoice(kind="none", name=None,
                                   result=f"(échec outil MCP {name}: {e})"),
                        tokens)

        return ToolChoice(kind="none", name=None), tokens

    def between_steps(self, goal: str, context: str, last_result: str):
        """Hook exécuté ENTRE deux étapes : permet d'invoquer un outil MCP
        (typiquement `say`) sans que ce soit lié à l'exécution d'une étape.

        Deux niveaux :
          1. le LLM décide (prompt between_steps) — n'importe quel outil MCP ;
          2. garantie déterministe : si l'objectif demande de raconter/dire et
             qu'un outil `/say` existe, on prononce le résultat même si le LLM
             a répondu "none". Ainsi `say` se lance de façon fiable.

        Retourne (ToolChoice, tokens_consommés).
        """
        catalog = self.mcp.catalog()   # seuls les outils MCP ont un effet de bord
        if not catalog:
            return ToolChoice(kind="none", name=None), 0

        catalog_text = json.dumps(catalog, ensure_ascii=False, indent=2)
        messages = [
            Message("system", self._between_prompt),
            Message("user", f"OBJECTIF:\n{goal}\n\nCONTEXTE:\n{context}\n\n"
                            f"RÉSULTAT DE L'ÉTAPE:\n{last_result}\n\n"
                            f"CATALOGUE:\n{catalog_text}"),
        ]
        decision, tokens = ask_json(self.llm, messages)

        if decision.get("use") == "mcp" and decision.get("name"):
            name = decision["name"]
            try:
                output = self.mcp.call(name, decision.get("arguments", {}))
                return (ToolChoice(kind="mcp", name=name, result=output,
                                   label=f"mcp:{name}"), tokens)
            except Exception as e:
                return (ToolChoice(kind="none", name=None,
                                   result=f"(échec outil MCP {name}: {e})"), tokens)

        # Garantie déterministe pour les objectifs de narration.
        if wants_narration(goal):
            say_tool = self.find_mcp_tool("/say")
            if say_tool:
                try:
                    self.mcp.call(say_tool, {"text": last_result})
                    return (ToolChoice(kind="mcp", name=say_tool, result=last_result,
                                       label=f"mcp:{say_tool}"), tokens)
                except Exception as e:
                    return (ToolChoice(kind="none", name=None,
                                       result=f"(échec say: {e})"), tokens)

        return ToolChoice(kind="none", name=None), tokens