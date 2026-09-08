"""Configuration : réglages, chargement du .env et des meta-prompts."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
SKILLS_DIR = ROOT / "skills"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Charge un .env minimal (KEY=VALUE) dans os.environ, sans dépendance externe."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_prompt(name: str) -> str:
    """Lit un meta-prompt depuis prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


@dataclass
class Config:
    # LLM
    provider: str = "mock"          # "openai" | "azure" | "anthropic" | "mock"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""              # ex: https://api.openai.com/v1
    api_version: str = ""           # utile pour Azure
    temperature: float = 0.2
    max_output_tokens: int = 4096
    request_timeout: int = 300      # secondes (modèles locaux/cloud parfois lents)

    # Conditions d'arrêt
    token_budget: int = 20_000      # arrêt si dépassé
    max_steps: int = 12             # garde-fou

    # Sous-agents (une étape peut relancer la même boucle plan -> execute)
    max_depth: int = 1              # profondeur de récursion autorisée (0 = jamais)
    sub_agent_token_budget: int = 8_000   # budget d'un sous-agent (borné par le reste)

    # Méta-prompt composé à la volée avant une exécution, si utile
    dynamic_meta_prompt: bool = True

    # MCP
    mcp_config_path: Path = field(default=ROOT / "mcp_servers.json")

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        return cls(
            provider=os.environ.get("LLM_PROVIDER", "mock"),
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            api_key=os.environ.get("LLM_API_KEY", ""),
            base_url=os.environ.get("LLM_BASE_URL", ""),
            api_version=os.environ.get("LLM_API_VERSION", ""),
            temperature=float(os.environ.get("LLM_TEMPERATURE", "0.2")),
            max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4096")),
            request_timeout=int(os.environ.get("LLM_REQUEST_TIMEOUT", "300")),
            token_budget=int(os.environ.get("TOKEN_BUDGET", "20000")),
            max_steps=int(os.environ.get("MAX_STEPS", "12")),
            max_depth=int(os.environ.get("MAX_DEPTH", "1")),
            sub_agent_token_budget=int(os.environ.get("SUB_AGENT_TOKEN_BUDGET", "8000")),
            dynamic_meta_prompt=os.environ.get("DYNAMIC_META_PROMPT", "1") not in ("0", "false", "False", ""),
        )
