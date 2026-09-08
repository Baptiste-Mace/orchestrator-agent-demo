"""Petits utilitaires partagés."""
from __future__ import annotations

import json
from typing import Any, List, Tuple

from .llm import LLMProvider, Message


def extract_json(text: str) -> Any:
    """Extrait le premier objet JSON d'une réponse LLM.

    Les modèles encadrent parfois le JSON avec du texte ou des blocs markdown
    (y compris des ```bash à l'intérieur du contenu). On utilise `raw_decode`,
    qui respecte correctement les chaînes et les accolades imbriquées : on tente
    de décoder à partir de chaque '{' jusqu'à trouver un objet JSON valide.
    """
    text = text.strip()
    decoder = json.JSONDecoder()

    # Cas simple : la réponse EST déjà du JSON pur.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Sinon : on cherche le premier '{' qui amorce un objet JSON décodable.
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            return obj
        except json.JSONDecodeError:
            idx = text.find("{", idx + 1)

    raise ValueError(
        "Aucun JSON valide trouvé (réponse peut-être tronquée si le modèle a "
        "atteint sa limite de sortie : augmente LLM_MAX_OUTPUT_TOKENS).\n"
        f"Réponse:\n{text}"
    )


def ask_json(llm: LLMProvider, messages: List[Message],
             retries: int = 2) -> Tuple[Any, int]:
    """Interroge le LLM et garantit un JSON exploitable (auto-correction).

    Les petits modèles locaux renvoient parfois un JSON tronqué ou malformé.
    En cas d'échec de parsing, on renvoie l'erreur au modèle et on redemande.
    Retourne (données, total_tokens_consommés sur toutes les tentatives).
    """
    total_tokens = 0
    conversation = list(messages)
    last_error = ""

    for _ in range(retries + 1):
        resp = llm.complete(conversation)
        total_tokens += resp.total_tokens
        try:
            return extract_json(resp.text), total_tokens
        except ValueError as e:
            last_error = str(e)
            conversation = messages + [
                Message("assistant", resp.text[:800]),
                Message("user",
                        "Ta réponse précédente n'était pas un JSON valide et complet. "
                        "Renvoie UNIQUEMENT l'objet JSON, complet, valide, sans texte "
                        "ni balises markdown autour."),
            ]

    raise ValueError(f"Impossible d'obtenir un JSON valide après {retries + 1} "
                     f"tentatives. Dernière erreur:\n{last_error}")
