"""Mini-client MCP (Model Context Protocol) via stdio, en stdlib pure.

Le transport stdio de MCP = messages JSON-RPC 2.0 délimités par des retours ligne.
On implémente juste ce qu'il faut pour une démo :
  initialize -> notifications/initialized -> tools/list -> tools/call

Volontairement synchrone et lisible : un serveur = un sous-processus, on écrit
une requête sur stdin, on lit les lignes de stdout jusqu'à la réponse attendue.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    """Gère un seul serveur MCP lancé en sous-processus (transport stdio)."""

    def __init__(self, name: str, command: str, args: List[str], env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.proc: Optional[subprocess.Popen] = None
        self._next_id = 0
        self._lock = threading.Lock()
        self.tools: List[dict] = []

    # --- cycle de vie ---------------------------------------------------------
    def start(self) -> None:
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self.env,
            text=True,
            bufsize=1,
        )
        self._initialize()
        self.tools = self._list_tools()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    # --- JSON-RPC bas niveau --------------------------------------------------
    def _send(self, message: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def _request(self, method: str, params: Optional[dict] = None) -> dict:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method,
                        "params": params or {}})
            # On lit jusqu'à trouver la réponse avec notre id (on ignore les
            # notifications / logs éventuels émis par le serveur entre-temps).
            assert self.proc and self.proc.stdout
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"[{self.name}] serveur MCP fermé prématurément")
                line = line.strip()
                if not line:
                    continue
                msg = json.loads(line)
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"[{self.name}] MCP error: {msg['error']}")
                    return msg.get("result", {})

    def _notify(self, method: str, params: Optional[dict] = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # --- handshake + capacités ------------------------------------------------
    def _initialize(self) -> None:
        self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "orchestrator-agent-demo", "version": "0.1.0"},
        })
        self._notify("notifications/initialized")

    def _list_tools(self) -> List[dict]:
        result = self._request("tools/list")
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        # Le contenu MCP est une liste de blocs {type, text, ...} : on aplatit le texte.
        parts = []
        for block in result.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)


class MCPManager:
    """Charge la config, démarre les serveurs, agrège les outils, dispatche les appels."""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.servers: Dict[str, MCPServer] = {}

    def start(self) -> None:
        if not self.config_path.exists():
            return
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        for name, spec in cfg.get("mcpServers", {}).items():
            if not isinstance(spec, dict) or "command" not in spec:
                continue  # ignore les entrées de commentaire / mal formées
            server = MCPServer(
                name=name,
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env"),
            )
            try:
                server.start()
                self.servers[name] = server
            except Exception as e:
                print(f"  ! Impossible de démarrer le serveur MCP '{name}': {e}")

    def stop(self) -> None:
        for server in self.servers.values():
            server.stop()

    def catalog(self) -> List[dict]:
        """Liste unifiée des outils MCP disponibles, préfixés par le nom du serveur."""
        items = []
        for name, server in self.servers.items():
            for tool in server.tools:
                items.append({
                    "type": "mcp",
                    "name": f"{name}/{tool['name']}",
                    "description": tool.get("description", ""),
                    "schema": tool.get("inputSchema", {}),
                })
        return items

    def call(self, qualified_name: str, arguments: dict) -> str:
        """Appelle un outil désigné par '<serveur>/<outil>'."""
        server_name, _, tool_name = qualified_name.partition("/")
        server = self.servers.get(server_name)
        if not server:
            raise RuntimeError(f"Serveur MCP inconnu : {server_name}")
        return server.call_tool(tool_name, arguments)
