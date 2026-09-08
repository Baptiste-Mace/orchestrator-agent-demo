"""Exécution d'une étape.

Chaque exécution :
  1. consulte la boîte à outils (skill/MCP pertinent ?) -> contexte enrichi,
  2. reçoit le contexte enrichi (plan + étapes faites + fichiers),
  3. produit un résultat et d'éventuels fichiers.
"""
from __future__ import annotations

from .config import load_prompt
from .context import AgentContext, StepRecord
from .llm import LLMProvider, Message
from .tools import Toolbox
from .util import ask_json


def execute_step(llm: LLMProvider, toolbox: Toolbox, ctx: AgentContext,
                 index: int, step: str) -> StepRecord:
    # 1) Sélection éventuelle d'une skill / d'un outil MCP avant l'exécution.
    choice, sel_tokens = toolbox.select_for(step, ctx.enriched_context())
    ctx.add_tokens(sel_tokens)

    tool_block = ""
    if choice.kind == "skill":
        tool_block = f"\n\nSKILL À APPLIQUER:\n{choice.result}"
    elif choice.kind == "mcp":
        tool_block = f"\n\nRÉSULTAT DE L'OUTIL MCP ({choice.name}):\n{choice.result}"

    # 2) Exécution proprement dite, nourrie par le contexte enrichi.
    messages = [
        Message("system", load_prompt("executor")),
        Message("user",
                f"{ctx.enriched_context()}\n\n"
                f"ÉTAPE À RÉALISER MAINTENANT (#{index}):\n{step}{tool_block}"),
    ]
    resp_data, tokens = ask_json(llm, messages)
    ctx.add_tokens(tokens)
    data = resp_data

    # 3) Écriture des fichiers produits dans le workspace.
    written = []
    for f in data.get("files", []):
        path = f.get("path")
        content = f.get("content", "")
        if path:
            ctx.write_file(path, content)
            written.append(path)

    return StepRecord(
        index=index,
        step=step,
        result=data.get("result", ""),
        tool_used=choice.label,
        files=written,
        notes=data.get("notes", ""),
    )
