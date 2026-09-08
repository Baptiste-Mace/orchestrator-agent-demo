"""Planification : un aller-retour avec le LLM pour transformer l'objectif en plan."""
from __future__ import annotations

from typing import List

from .config import load_prompt
from .context import AgentContext
from .llm import LLMProvider, Message
from .util import ask_json


def make_plan(llm: LLMProvider, ctx: AgentContext) -> List[str]:
    """Demande un plan au LLM, met à jour le budget de tokens, renvoie les étapes."""
    messages = [
        Message("system", load_prompt("planner")),
        Message("user", f"OBJECTIF:\n{ctx.goal}"),
    ]
    data, tokens = ask_json(llm, messages)
    ctx.add_tokens(tokens)

    plan = [str(step) for step in data.get("plan", []) if str(step).strip()]
    if not plan:
        raise RuntimeError("Le planificateur n'a produit aucune étape.")
    return plan
