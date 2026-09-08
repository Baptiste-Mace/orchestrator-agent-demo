# Orchestrator Agent Demo

Un **agent orchestrateur minimal et pédagogique** en Python. Objectif : montrer,
avec le moins de code possible, **comment fonctionne un agent** qui fait des
aller-retours entre son contexte et un LLM.

Boucle : **planifier → (choisir une skill / un outil MCP) → exécuter**, jusqu'à ce que
le plan soit terminé **ou** que le budget de tokens soit atteint.

- 🐍 **Python 3.9+**, **zéro dépendance** (bibliothèque standard uniquement).
- 🧠 Provider LLM **abstrait** derrière une interface (OpenAI / Azure / Anthropic / Ollama local / Mock offline).
- 🔌 **Vraie intégration MCP** : mini-client du protocole (JSON-RPC sur stdio) fait maison.
- 📝 **Meta-prompts dans des fichiers séparés** (`prompts/`) pour la lisibilité.

## Idée en une image

```
        OBJECTIF
           │
           ▼
   ┌───────────────┐   aller-retour LLM
   │  PLANIFICATION │  ───────────────►  plan = [étape 1, étape 2, ...]
   └───────────────┘
           │
           ▼
   pour chaque étape (tant que budget de tokens OK) :
   ┌────────────────────────────────────────────────────────┐
   │  1. SÉLECTION  : une skill / un outil MCP est-il utile ? │  ◄── catalogue skills + MCP
   │  2. EXÉCUTION  : réalise l'étape avec le CONTEXTE ENRICHI │  ◄── plan + étapes faites + fichiers
   │  3. ENRICHIT   : résultat + fichiers créés → contexte     │  ──► réinjecté à l'étape suivante
   └────────────────────────────────────────────────────────┘
           │
           ▼
   ARRÊT : plan terminé  OU  budget de tokens atteint
```

## Installation

Aucune installation de paquet Python n'est requise.

```bash
cd orchestrator-agent-demo
cp .env.example .env      # optionnel : par défaut le provider "mock" tourne hors-ligne
```

## Utilisation

Démo hors-ligne immédiate (provider `mock`, aucune clé nécessaire) :

```bash
python run.py "Rédiger un court guide de démarrage pour un nouveau développeur"
```

Avec un vrai LLM : édite `.env` (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, ...).

### Ollama (LLM local, aucune clé)

L'agent parle à Ollama via son API REST (`/api/chat`), sans bibliothèque tierce :

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1          # ou le modèle que tu as (ex: gemma3, mistral...)
LLM_BASE_URL=http://localhost:11434
```

> Astuce : les petits modèles locaux renvoient parfois un JSON tronqué ou entouré de
> texte. L'agent gère ça de deux façons — `LLM_MAX_OUTPUT_TOKENS` (assez grand pour que
> le contenu des fichiers tienne) et une **auto-correction** : si le JSON est invalide,
> l'agent le redemande au modèle (voir `ask_json` dans `agent/util.py`). Pour un modèle
> lent ou `-cloud`, augmente `LLM_REQUEST_TIMEOUT`.

```bash
# exemple OpenAI
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...

# exemple Ollama (local, aucune clé)
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
LLM_BASE_URL=http://localhost:11434
```

L'agent affiche chaque phase (plan, exécution, tokens) et dépose les fichiers
qu'il crée dans `workspace/<horodatage>/`.

## Skills et MCP

Avant chaque étape, l'agent consulte un **catalogue de capacités** et demande au LLM
(`prompts/tool_selection.md`) s'il faut en utiliser une :

- **Skills locales** : décrites dans `skills/skills.json`, chacune pointant vers un
  fichier d'instructions (`skills/*.md`). Une skill injecte une consigne spécialisée.
- **Outils MCP** : de vrais serveurs MCP déclarés dans `mcp_servers.json`, lancés en
  sous-processus (transport stdio). Leurs outils sont listés puis appelés réellement.

Activer un serveur MCP (exemple filesystem, nécessite Node/`npx`) :

```bash
cp mcp_servers.example.json mcp_servers.json
```

Le mini-client MCP (`agent/mcp_client.py`) implémente la séquence du protocole :
`initialize` → `notifications/initialized` → `tools/list` → `tools/call`.

### MCP maison inclus : « macOS Toolkit »

`mcp_servers/macos_toolkit.py` est un **serveur MCP fait maison** (stdlib pure) qui
donne à l'agent des capacités concrètes sur ton Mac. Active-le en copiant la config
d'exemple (`mcp_servers.json` est local et ignoré par git) :

```bash
cp mcp_servers.example.json mcp_servers.json
```

Outils exposés :

| Outil            | Effet                                    | Commande système |
|------------------|------------------------------------------|------------------|
| `notify`         | Notification système macOS               | `osascript`      |
| `say`            | Le Mac prononce un texte                 | `say`            |
| `clipboard_get`  | Lit le presse-papier                     | `pbpaste`        |
| `clipboard_set`  | Écrit dans le presse-papier              | `pbcopy`         |

Exemple d'objectif qui déclenche ces outils :

```bash
python run.py "Génère une courte citation motivante, copie-la dans le presse-papier \
avec l'outil clipboard, puis affiche une notification macOS annonçant qu'elle est prête"
```

L'agent planifie, puis pour l'étape « copier » et l'étape « notifier » il **choisit
lui-même** `mcp:macos/clipboard_set` et `mcp:macos/notify`, en construisant les
arguments à partir du contexte enrichi (le vrai texte généré à l'étape précédente).

C'est aussi un patron réutilisable : pour créer ton propre MCP, copie ce fichier,
remplace la liste `TOOLS` et les `HANDLERS`, puis déclare-le dans `mcp_servers.json`.

## Structure

```
orchestrator-agent-demo/
├── run.py                  point d'entrée
├── prompts/                meta-prompts (planner, executor, tool_selection)
├── skills/                 skills locales (registre + fichiers d'instructions)
├── mcp_servers.json        serveurs MCP à démarrer
├── mcp_servers/
│   └── macos_toolkit.py    serveur MCP maison (notify/say/clipboard)
└── agent/
    ├── config.py           réglages + chargement .env/prompts
    ├── llm.py              interface LLMProvider + OpenAI/Anthropic/Mock
    ├── context.py          AgentContext : plan, historique, fichiers, budget tokens
    ├── mcp_client.py       mini-client MCP (JSON-RPC stdio) + manager
    ├── tools.py            catalogue skills+MCP + sélection avant exécution
    ├── planner.py          construit le plan via le LLM
    ├── executor.py         exécute une étape avec contexte enrichi + outil éventuel
    └── orchestrator.py     la boucle et les conditions d'arrêt
```

## Conditions d'arrêt

- **Plan terminé** : toutes les étapes ont été exécutées.
- **Budget de tokens atteint** : `TOKEN_BUDGET` (chaque appel LLM incrémente le compteur).
- Garde-fou supplémentaire : `MAX_STEPS`.

## Pour aller plus loin

Idées d'extensions gardées volontairement hors du périmètre pour rester lisible :
re-planification dynamique, mémoire long terme, validation/critique des étapes,
parallélisation, plusieurs outils MCP par étape.
