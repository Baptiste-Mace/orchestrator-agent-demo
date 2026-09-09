"""Exécution d'une étape.

Chaque exécution :
  1. consulte la boîte à outils (skill/MCP pertinent ?) -> contexte enrichi,
  2. compose éventuellement un méta-prompt spécialisé pour l'étape,
  3. reçoit le contexte enrichi (plan + étapes faites + fichiers),
  4. produit un résultat et d'éventuels fichiers.
"""
from __future__ import annotations

from .config import Config
from .context import AgentContext, StepRecord
from .llm import LLMProvider, Message
from .metaprompt import compose_system_prompt
from .tools import Toolbox
from .util import ask_json


def execute_step(llm: LLMProvider, toolbox: Toolbox, ctx: AgentContext,
                 index: int, step: str, cfg: Config) -> StepRecord:
    # 1) Sélection éventuelle d'une skill / d'un outil MCP avant l'exécution.
    choice, sel_tokens = toolbox.select_for(step, ctx.enriched_context())
    ctx.add_tokens(sel_tokens)

    tool_block = ""
    tool_output = ""
    if choice.kind == "skill":
        tool_block = f"\n\nSKILL À APPLIQUER:\n{choice.result}"
    elif choice.kind == "mcp":
        tool_block = f"\n\nRÉSULTAT DE L'OUTIL MCP ({choice.name}):\n{choice.result}"
        tool_output = choice.result   # conservé dans le contexte pour la suite

    # 2) Méta-prompt composé à la volée : le prompt de base, enrichi si utile.
    system_prompt, specialisation, meta_tokens = compose_system_prompt(
        llm, ctx, step, enabled=cfg.dynamic_meta_prompt)
    ctx.add_tokens(meta_tokens)

    # 3) Exécution proprement dite, nourrie par le contexte enrichi.
    messages = [
        Message("system", system_prompt),
        Message("user",
                f"{ctx.enriched_context()}\n\n"
                f"ÉTAPE À RÉALISER MAINTENANT (#{index}):\n{step}{tool_block}"),
    ]
    resp_data, tokens = ask_json(llm, messages)
    ctx.add_tokens(tokens)
    data = resp_data

    # 4) Écriture des fichiers produits dans le workspace.
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
        meta_prompt=specialisation,
        tool_output=tool_output,
    )
