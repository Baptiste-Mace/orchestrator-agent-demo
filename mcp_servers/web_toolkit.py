#!/usr/bin/env python3
"""Serveur MCP maison : "Web Toolkit".

Donne à l'agent une fenêtre simple sur le web, sans clé API ni dépendance :
  - web_search(query, max_results?) -> liste de résultats (titre, url, extrait)
  - web_fetch(url, max_chars?)      -> texte lisible d'une page (balises retirées)

La recherche passe par la version HTML de DuckDuckGo (html.duckduckgo.com), qui
se lit sans JavaScript ni clé, contrairement à la page Google. On reste ainsi
dans l'esprit du projet : quelques dizaines de lignes, la bibliothèque standard,
et rien d'autre.

C'est un vrai serveur MCP : JSON-RPC 2.0 sur stdio (messages délimités par des
retours ligne), séquence initialize -> initialized -> tools/list -> tools/call.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2024-11-05"
USER_AGENT = "Mozilla/5.0 (compatible; orchestrator-agent-demo/1.0)"
SEARCH_URL = "https://html.duckduckgo.com/html/"


# --- Catalogue des outils exposés par ce serveur ----------------------------
TOOLS = [
    {
        "name": "web_search",
        "description": ("Recherche sur le web (via DuckDuckGo) et retourne une liste "
                        "de résultats : titre, url, extrait. À utiliser pour trouver "
                        "des informations récentes ou factuelles avant d'agir."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "La requête à rechercher"},
                "max_results": {"type": "integer",
                                "description": "Nombre de résultats (défaut 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": ("Télécharge une page web et renvoie son texte lisible (balises "
                        "HTML retirées). À utiliser pour lire une url trouvée par "
                        "web_search et nourrir le contexte."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "L'adresse de la page à lire"},
                "max_chars": {"type": "integer",
                              "description": "Longueur max du texte (défaut 10000)"},
            },
            "required": ["url"],
        },
    },
]


# --- Petites fonctions de nettoyage HTML ------------------------------------
def strip_tags(fragment: str) -> str:
    """Retire les balises d'un fragment HTML et normalise les espaces."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def real_url(href: str) -> str:
    """DuckDuckGo enveloppe les liens dans /l/?uddg=<url encodée>. On la décode."""
    parsed = urllib.parse.urlparse(href)
    params = urllib.parse.parse_qs(parsed.query)
    if "uddg" in params:
        return params["uddg"][0]
    return href


def http_get(url: str, data: bytes = None) -> str:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# --- Implémentation des outils ----------------------------------------------
# Un résultat DuckDuckGo HTML : un lien de classe result__a, puis un extrait
# de classe result__snippet. On les capture avec des expressions régulières.
_RESULT_LINK = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RESULT_SNIPPET = re.compile(
    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)


def tool_web_search(args: dict) -> str:
    query = args.get("query", "").strip()
    if not query:
        return "Requête vide."
    max_results = int(args.get("max_results", 5))

    body = urllib.parse.urlencode({"q": query}).encode()
    page = http_get(SEARCH_URL, data=body)

    links = _RESULT_LINK.findall(page)
    snippets = _RESULT_SNIPPET.findall(page)

    lines = []
    for i, (href, title) in enumerate(links[:max_results]):
        url = real_url(href)
        snippet = strip_tags(snippets[i]) if i < len(snippets) else ""
        lines.append(f"{i + 1}. {strip_tags(title)}\n   {url}\n   {snippet}")

    if not lines:
        return f"Aucun résultat pour : {query}"
    return f"Résultats pour « {query} » :\n\n" + "\n\n".join(lines)


def tool_web_fetch(args: dict) -> str:
    url = args.get("url", "").strip()
    if not url:
        return "URL vide."
    max_chars = int(args.get("max_chars", 10000))

    page = http_get(url)
    # On retire d'abord les blocs script/style (bruit non lisible).
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)

    # Beaucoup de pages (accueils de journaux, blogs) mettent leurs titres dans
    # des balises de titre h1..h3. Les extraire évite de ne capter que le menu de
    # navigation quand on tronque une très longue page.
    headings = []
    for tag in ("h1", "h2", "h3"):
        for frag in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", page, re.S | re.I):
            t = strip_tags(frag)
            if t and t not in headings:
                headings.append(t)

    text = strip_tags(page)
    if len(text) > max_chars:
        text = text[:max_chars] + " […]"

    out = [f"Contenu de {url} :"]
    if headings:
        titles = "\n".join(f"- {h}" for h in headings[:20])
        out.append(f"\nTITRES DÉTECTÉS (h1-h3) :\n{titles}")
    out.append(f"\nTEXTE :\n{text}")
    return "\n".join(out)


HANDLERS = {
    "web_search": tool_web_search,
    "web_fetch": tool_web_fetch,
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
            "serverInfo": {"name": "web-toolkit", "version": "0.1.0"},
        })
    elif method == "notifications/initialized":
        pass
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
