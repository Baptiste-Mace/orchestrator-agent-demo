#!/usr/bin/env python3
"""Serveur MCP maison : "macOS Toolkit".

Donne à l'agent des capacités concrètes sur un Mac, via des commandes système
standard (aucune dépendance) :
  - notify(title, message)   -> notification macOS (osascript)
  - say(text, voice?)        -> synthèse vocale (commande `say`)
  - clipboard_get()          -> lit le presse-papier (pbpaste)
  - clipboard_set(text)      -> écrit dans le presse-papier (pbcopy)

C'est un vrai serveur MCP : il parle le protocole JSON-RPC 2.0 sur stdio
(messages délimités par des retours ligne) et implémente la séquence :
  initialize -> notifications/initialized -> tools/list -> tools/call

Lance-le seul pour voir : il attend du JSON-RPC sur stdin.
"""
from __future__ import annotations

import json
import subprocess
import sys

PROTOCOL_VERSION = "2024-11-05"

# --- Catalogue des outils exposés par ce serveur ----------------------------
TOOLS = [
    {
        "name": "notify",
        "description": "Affiche une notification système macOS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Titre de la notification"},
                "message": {"type": "string", "description": "Corps du message"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "say",
        "description": "Fait parler le Mac (synthèse vocale).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Texte à prononcer"},
                "voice": {"type": "string", "description": "Voix optionnelle (ex: Thomas, Amelie)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "clipboard_get",
        "description": "Retourne le contenu texte actuel du presse-papier.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "clipboard_set",
        "description": "Remplace le contenu du presse-papier par le texte fourni.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Texte à copier"}},
            "required": ["text"],
        },
    },
]


# --- Implémentation des outils ----------------------------------------------
def tool_notify(args: dict) -> str:
    title = args.get("title", "Agent")
    message = args.get("message", "")
    # osascript attend une chaîne : on échappe les guillemets.
    safe_msg = message.replace('"', '\\"')
    safe_title = title.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    subprocess.run(["osascript", "-e", script], check=True)
    return f"Notification affichée : [{title}] {message}"


def tool_say(args: dict) -> str:
    text = args.get("text", "")
    cmd = ["say"]
    if args.get("voice"):
        cmd += ["-v", args["voice"]]
    cmd.append(text)
    subprocess.run(cmd, check=True)
    return f"Prononcé : {text}"


def tool_clipboard_get(args: dict) -> str:
    out = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
    return out.stdout


def tool_clipboard_set(args: dict) -> str:
    text = args.get("text", "")
    subprocess.run(["pbcopy"], input=text, text=True, check=True)
    return f"Presse-papier mis à jour ({len(text)} caractères)."


HANDLERS = {
    "notify": tool_notify,
    "say": tool_say,
    "clipboard_get": tool_clipboard_get,
    "clipboard_set": tool_clipboard_set,
}


# --- Boucle JSON-RPC sur stdio ----------------------------------------------
def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def reply(req_id, result) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "result": result})


def reply_error(req_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        reply(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "macos-toolkit", "version": "0.1.0"},
        })
    elif method == "notifications/initialized":
        pass  # notification : pas de réponse attendue
    elif method == "tools/list":
        reply(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if not handler:
            reply_error(req_id, -32601, f"Outil inconnu : {name}")
            return
        try:
            text = handler(args)
            reply(req_id, {"content": [{"type": "text", "text": text}]})
        except Exception as e:
            # On renvoie l'erreur comme contenu d'outil (isError) plutôt que de crasher.
            reply(req_id, {"content": [{"type": "text", "text": f"Erreur: {e}"}],
                           "isError": True})
    elif req_id is not None:
        reply_error(req_id, -32601, f"Méthode non supportée : {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
