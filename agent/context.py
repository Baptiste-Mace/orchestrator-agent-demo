"""Le contexte partagé de l'agent : ce qui circule entre planification et exécutions.

C'est le "carnet" de l'agent. Chaque étape le lit (contexte enrichi) et l'enrichit
(résultats, fichiers créés, tokens consommés).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class StepRecord:
    index: int
    step: str
    result: str
    tool_used: str = "none"   # "none" | "skill:<nom>" | "mcp:<serveur>/<outil>" | "sub-agent"
    files: List[str] = field(default_factory=list)
    notes: str = ""
    meta_prompt: str = ""     # spécialisation injectée dans le prompt (si générée)
    tool_output: str = ""     # sortie brute de l'outil (ex: résultats web) à conserver


@dataclass
class AgentContext:
    goal: str
    workspace: Path
    token_budget: int
    tokens_used: int = 0
    plan: List[str] = field(default_factory=list)
    history: List[StepRecord] = field(default_factory=list)
    files: Dict[str, str] = field(default_factory=dict)   # chemin -> résumé/aperçu

    # --- budget de tokens : condition d'arrêt ---------------------------------
    def add_tokens(self, n: int) -> None:
        self.tokens_used += n

    @property
    def remaining_budget(self) -> int:
        return self.token_budget - self.tokens_used

    def budget_exhausted(self) -> bool:
        return self.tokens_used >= self.token_budget

    def summary(self) -> str:
        """Résumé compact de ce que l'agent a accompli (utile pour un sous-agent
        qui doit rendre un résultat unique à son parent)."""
        done = [r.result for r in self.history if r.result]
        if not done:
            return "(aucune étape aboutie)"
        return " ".join(done)

    # --- enrichissement -------------------------------------------------------
    def record_step(self, record: StepRecord) -> None:
        self.history.append(record)
        for f in record.files:
            self.files[f] = f"créé à l'étape {record.index}"

    def write_file(self, rel_path: str, content: str) -> str:
        """Écrit un fichier produit par une étape dans le workspace."""
        target = self.workspace / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    # --- vue compacte injectée dans les prompts d'exécution -------------------
    def enriched_context(self) -> str:
        lines = [f"OBJECTIF: {self.goal}", "", "PLAN:"]
        for i, step in enumerate(self.plan):
            lines.append(f"  {i + 1}. {step}")

        lines.append("")
        lines.append("ÉTAPES DÉJÀ RÉALISÉES:")
        if not self.history:
            lines.append("  (aucune pour l'instant)")
        for r in self.history:
            lines.append(f"  [{r.index}] {r.step}")
            lines.append(f"      → résultat: {r.result}")
            if r.tool_used != "none":
                lines.append(f"      → outil: {r.tool_used}")
            if r.tool_output:
                # On conserve les données brutes récupérées (ex: résultats web),
                # tronquées, pour que les étapes suivantes s'appuient sur du réel.
                snippet = r.tool_output.strip()
                if len(snippet) > 10000:
                    snippet = snippet[:10000] + " […]"
                lines.append(f"      → données récupérées:\n{snippet}")
            if r.notes:
                lines.append(f"      → notes: {r.notes}")

        lines.append("")
        lines.append("FICHIERS CRÉÉS:")
        if not self.files:
            lines.append("  (aucun)")
        for path, info in self.files.items():
            lines.append(f"  - {path} ({info})")

        return "\n".join(lines)
