"""L'orchestrateur : la boucle plan -> execute avec les conditions d'arrêt.

Conditions d'arrêt :
  - toutes les étapes du plan ont été exécutées, OU
  - le budget de tokens est atteint (garde-fou max_steps en plus).

Une étape peut, si elle est composite, être déléguée à un SOUS-AGENT : la même boucle,
relancée avec l'étape comme objectif, son propre budget de tokens, et une profondeur
incrémentée (bornée par cfg.max_depth pour éviter toute récursion infinie).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Config, load_prompt
from .context import AgentContext, StepRecord
from .executor import execute_step
from .llm import LLMProvider, Message
from .planner import make_plan
from .tools import Toolbox
from .util import ask_json


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
    def __init__(self, cfg: Config, llm: LLMProvider, toolbox: Toolbox,
                 workspace: Path, depth: int = 0):
        self.cfg = cfg
        self.llm = llm
        self.toolbox = toolbox
        self.workspace = workspace
        self.depth = depth
        self.prefix = "   " * depth   # indentation des logs selon la profondeur

    # -- API publique : lance l'agent sur un objectif ------------------------
    def run(self, goal: str, token_budget: Optional[int] = None) -> RunReport:
        budget = token_budget if token_budget is not None else self.cfg.token_budget
        ctx = AgentContext(goal=goal, workspace=self.workspace, token_budget=budget)
        return self._run(ctx)

    # -- Boucle interne (partagée entre agent racine et sous-agents) ---------
    def _run(self, ctx: AgentContext) -> RunReport:
        p = self.prefix

        # --- Phase 1 : planification (un aller-retour LLM) ------------------
        print(f"\n{p}=== PLANIFICATION{self._tag()} ===")
        ctx.plan = make_plan(self.llm, ctx)
        for i, step in enumerate(ctx.plan, 1):
            print(f"{p}  {i}. {step}")
        print(f"{p}  (tokens: {ctx.tokens_used}/{ctx.token_budget})")

        # --- Phase 2 : exécution étape par étape ---------------------------
        print(f"\n{p}=== EXÉCUTION{self._tag()} ===")
        stop_reason = "plan terminé"
        steps_done = 0

        for index, step in enumerate(ctx.plan, 1):
            if ctx.budget_exhausted():
                stop_reason = "budget de tokens atteint"
                break
            if index > self.cfg.max_steps:
                stop_reason = "garde-fou max_steps atteint"
                break

            print(f"\n{p}-- Étape {index}/{len(ctx.plan)} : {step}")

            # Cette étape est-elle un objectif à part entière ? -> sous-agent.
            if self.depth < self.cfg.max_depth and self._should_delegate(ctx, step):
                print(f"{p}   -> déléguée à un sous-agent")
                record = self._delegate(ctx, index, step)
            else:
                record = execute_step(self.llm, self.toolbox, ctx, index, step, self.cfg)

            ctx.record_step(record)
            steps_done += 1

            print(f"{p}   outil : {record.tool_used}")
            if record.meta_prompt:
                print(f"{p}   méta-prompt spécialisé : oui")
            print(f"{p}   résultat : {record.result}")
            if record.files:
                print(f"{p}   fichiers : {', '.join(record.files)}")
            print(f"{p}   (tokens: {ctx.tokens_used}/{ctx.token_budget})")

            # --- Hook ENTRE-ÉTAPES : effet de bord optionnel (ex: say) ------
            between, btokens = self.toolbox.between_steps(
                ctx.goal, ctx.enriched_context(), record.result)
            ctx.add_tokens(btokens)
            if between.kind != "none":
                print(f"{p}   entre-étapes : {between.label}")

        return RunReport(
            goal=ctx.goal,
            stop_reason=stop_reason,
            steps_done=steps_done,
            steps_total=len(ctx.plan),
            tokens_used=ctx.tokens_used,
            token_budget=ctx.token_budget,
            workspace=str(self.workspace),
        )

    # -- Décision de délégation ---------------------------------------------
    def _should_delegate(self, ctx: AgentContext, step: str) -> bool:
        messages = [
            Message("system", load_prompt("delegation")),
            Message("user", f"CONTEXTE:\n{ctx.enriched_context()}\n\nÉTAPE:\n{step}"),
        ]
        data, tokens = ask_json(self.llm, messages)
        ctx.add_tokens(tokens)
        return bool(data.get("delegate", False))

    # -- Exécution d'une étape via un sous-agent ----------------------------
    def _delegate(self, parent_ctx: AgentContext, index: int, step: str) -> StepRecord:
        """Relance la même boucle sur `step`, avec son propre budget, puis rend
        un résultat unique au parent. Les tokens du sous-agent sont décomptés du
        budget du parent ; les fichiers produits remontent dans le contexte parent.
        """
        sub_budget = min(self.cfg.sub_agent_token_budget, parent_ctx.remaining_budget)
        child = Orchestrator(self.cfg, self.llm, self.toolbox, self.workspace,
                             depth=self.depth + 1)
        child_ctx = AgentContext(goal=step, workspace=self.workspace,
                                 token_budget=sub_budget)
        child._run(child_ctx)

        parent_ctx.add_tokens(child_ctx.tokens_used)
        files = [f for r in child_ctx.history for f in r.files]
        return StepRecord(
            index=index,
            step=step,
            result=child_ctx.summary(),
            tool_used="sub-agent",
            files=files,
            notes=f"sous-agent : {len(child_ctx.history)} étape(s)",
        )

    def _tag(self) -> str:
        return "" if self.depth == 0 else f" (sous-agent, profondeur {self.depth})"
