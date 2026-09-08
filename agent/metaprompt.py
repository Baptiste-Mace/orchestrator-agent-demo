"""Composition du méta-prompt à la volée.

Le module d'exécution part d'un méta-prompt générique (prompts/executor.md). Ici, on
lui ajoute, SI C'EST UTILE, un complément d'instructions spécialisé pour l'étape
courante : le bon prompt dépend du contexte du moment, pas seulement d'un fichier figé.

La décision (« needed ») est prise par le LLM via prompts/meta_prompt.md. Si rien
n'est nécessaire, on renvoie simplement le prompt de base : coût quasi nul, comportement
identique à avant.
"""
from __future__ import annotations

from typing import Tuple

from .config import load_prompt
from .context import AgentContext
from .llm import LLMProvider, Message
from .util import ask_json

SEPARATOR = "\n\n--- SPÉCIALISATION POUR CETTE ÉTAPE ---\n"


def compose_system_prompt(llm: LLMProvider, ctx: AgentContext, step: str,
                          base_name: str = "executor",
                          enabled: bool = True) -> Tuple[str, str, int]:
    """Renvoie (system_prompt, specialisation, tokens).

    - system_prompt : le prompt de base, éventuellement enrichi ;
    - specialisation : le complément ajouté (chaîne vide si aucun) ;
    - tokens : coût de la décision (0 si désactivé).
    """
    base = load_prompt(base_name)
    if not enabled:
        return base, "", 0

    messages = [
        Message("system", load_prompt("meta_prompt")),
        Message("user", f"CONTEXTE:\n{ctx.enriched_context()}\n\nÉTAPE:\n{step}"),
    ]
    data, tokens = ask_json(llm, messages)

    specialisation = str(data.get("meta_prompt", "")).strip()
    if data.get("needed") and specialisation:
        return base + SEPARATOR + specialisation, specialisation, tokens

    return base, "", tokens
