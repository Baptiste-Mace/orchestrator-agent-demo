"""L'orchestrateur : la boucle plan -> execute avec les conditions d'arrêt.

Conditions d'arrêt :
  - toutes les étapes du plan ont été exécutées, OU
  - le budget de tokens est atteint (garde-fou max_steps en plus).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .context import AgentContext
from .executor import execute_step
from .llm import LLMProvider
from .planner import make_plan
from .tools import Toolbox


@dataclass
class RunReport:
    goal: str
    stop_reason: str
    steps_done: int
    steps_total: int
    tokens_used: int
    token_budget: int
    workspace: str


class Orchestrator:
    def __init__(self, cfg: Config, llm: LLMProvider, toolbox: Toolbox, workspace: Path):
        self.cfg = cfg
        self.llm = llm
        self.toolbox = toolbox
        self.workspace = workspace

    def run(self, goal: str) -> RunReport:
        ctx = AgentContext(goal=goal, workspace=self.workspace,
                           token_budget=self.cfg.token_budget)

        # --- Phase 1 : planification (un aller-retour LLM) --------------------
        print("\n=== PLANIFICATION ===")
        ctx.plan = make_plan(self.llm, ctx)
        for i, step in enumerate(ctx.plan, 1):
            print(f"  {i}. {step}")
        print(f"  (tokens: {ctx.tokens_used}/{ctx.token_budget})")

        # --- Phase 2 : exécution étape par étape ------------------------------
        print("\n=== EXÉCUTION ===")
        stop_reason = "plan terminé"
        steps_done = 0

        for index, step in enumerate(ctx.plan, 1):
            if ctx.budget_exhausted():
                stop_reason = "budget de tokens atteint"
                break
            if index > self.cfg.max_steps:
                stop_reason = "garde-fou max_steps atteint"
                break

            print(f"\n-- Étape {index}/{len(ctx.plan)} : {step}")
            record = execute_step(self.llm, self.toolbox, ctx, index, step)
            ctx.record_step(record)
            steps_done += 1

            print(f"   outil : {record.tool_used}")
            print(f"   résultat : {record.result}")
            if record.files:
                print(f"   fichiers : {', '.join(record.files)}")
            print(f"   (tokens: {ctx.tokens_used}/{ctx.token_budget})")

        return RunReport(
            goal=goal,
            stop_reason=stop_reason,
            steps_done=steps_done,
            steps_total=len(ctx.plan),
            tokens_used=ctx.tokens_used,
            token_budget=ctx.token_budget,
            workspace=str(self.workspace),
        )
