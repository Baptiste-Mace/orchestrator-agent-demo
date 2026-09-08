#!/usr/bin/env python3
"""Point d'entrée de la démo.

Usage :
    python run.py "Ton objectif ici"
    python run.py                      # demande l'objectif de façon interactive
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from agent.config import Config
from agent.llm import make_provider
from agent.mcp_client import MCPManager
from agent.orchestrator import Orchestrator
from agent.tools import Toolbox, load_skills


def main() -> None:
    goal = " ".join(sys.argv[1:]).strip()
    if not goal:
        goal = input("Objectif de l'agent : ").strip()
    if not goal:
        print("Aucun objectif fourni.")
        return

    cfg = Config.from_env()

    # Workspace daté : c'est là que l'agent dépose les fichiers qu'il crée.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = Path(__file__).resolve().parent / "workspace" / stamp
    workspace.mkdir(parents=True, exist_ok=True)

    print(f"Provider : {cfg.provider} | modèle : {cfg.model}")
    print(f"Budget tokens : {cfg.token_budget} | workspace : {workspace}")

    llm = make_provider(cfg)

    # Démarre les serveurs MCP (le cas échéant) — vrais serveurs, vrai protocole.
    mcp = MCPManager(cfg.mcp_config_path)
    mcp.start()
    if mcp.servers:
        print(f"Serveurs MCP actifs : {', '.join(mcp.servers)}")

    try:
        toolbox = Toolbox(load_skills(), mcp, llm)
        orchestrator = Orchestrator(cfg, llm, toolbox, workspace)
        report = orchestrator.run(goal)

        print("\n=== RAPPORT ===")
        print(f"  Objectif       : {report.goal}")
        print(f"  Arrêt          : {report.stop_reason}")
        print(f"  Étapes         : {report.steps_done}/{report.steps_total}")
        print(f"  Tokens         : {report.tokens_used}/{report.token_budget}")
        print(f"  Fichiers dans  : {report.workspace}")
    finally:
        mcp.stop()


if __name__ == "__main__":
    main()
