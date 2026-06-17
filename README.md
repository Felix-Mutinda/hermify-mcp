# hermify-mcp

> Cross-agent, dataset-backed skill and memory sync via MCP.
> Hermify your agent interactions - push from Claude, pull into Gemini, improve without friction.

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![agentskills.io](https://img.shields.io/badge/skills-agentskills.io-purple)](https://agentskills.io)

---

## What it does

`hermify-mcp` is an MCP server that gives any agent runtime a shared, **event-sourced, dataset-backed** knowledge base following the [agentskills.io](https://agentskills.io) open standard. 

Instead of relying on traditional file-based version control, `hermify-mcp` treats agent skills, memory, and logs as structured, queryable data. It uses a **local-first DuckDB buffer** for lightning-fast, non-blocking agent interactions, which seamlessly syncs to **Hugging Face Datasets** as the immutable source of truth.

```text
Claude session ──► hermify_log() ──► Local DuckDB Buffer (Instant, ACID)
                                              │
                                        (Async Sync)
                                              │
                               Hugging Face Datasets (Parquet Shards)
                                              │
                              Gemini / Hermes / next Claude
                              session pulls & queries on start
```

**Non-intrusive by design.** The server never injects into the agent loop. Agents call `propose_skill` or `hermify_log` post-session. The main workflow is never blocked waiting for network sync.

---

## 🚀 Quick Start & Agent Setup

The recommended way to run `hermify-mcp` is via **`uvx`**, which allows your agent runtime to spawn the server in an isolated, ephemeral environment without polluting your global Python packages.

### 1. Bootstrap your local configuration (One-time setup)
Run this in your terminal to create your local DuckDB buffer and configure your Hugging Face target.

```bash
# Install uv if you haven't already (https://docs.astral.sh/uv/)
# Bootstrap local config (creates ~/.hermify/config.yaml)
uvx hermify-mcp init --hf-repo your-username/hermify-agent-memory --mode hf_push

# Optional: Enable YOLO auto-approval mode (uses LLM-as-a-Judge)
# uvx hermify-mcp init --hf-repo your-username/hermify-agent-memory --mode hf_push --yolo
```

### 2. Connect your Agent Runtime

#### Option A: Local Private Brain (Claude Desktop / Cursor / Windsurf)
Add the following to your MCP client configuration. This uses `uvx` to run the server locally via `stdio`. 

*Note: We inject `HF_TOKEN` via the `env` block so the server can sync to Hugging Face.*

**Claude Desktop (`claude_desktop_config.json`)** / **Cursor (`mcp.json`)**:
```json
{
  "mcpServers": {
    "hermify": {
      "command": "uvx",
      "args": ["hermify-mcp", "serve", "--transport", "stdio"],
      "env": {
        "HF_TOKEN": "hf_YOUR_HUGGINGFACE_TOKEN_HERE"
      }
    }
  }
}
```

#### Option B: Shared Team Brain (Hugging Face Spaces / Remote HTTP)
Want to host a centralized, team-wide agent brain or a public demo? You can deploy `hermify-mcp` to Hugging Face Spaces using Docker. 

This allows multiple agents (or multiple users) to connect to the same shared memory and skill library via HTTP, without needing to manage local files or sync conflicts.

👉 **[Read the full Docker Deployment Guide here](docs/DEPLOY_HF_SPACES.md)**

Once your Space is deployed and running, you don't use `uvx` or `stdio`. Instead, point your agent's MCP configuration directly to your Space's URL.

Update your agent's MCP configuration (e.g., `claude_desktop_config.json` or Cursor's `mcp.json`):

```json
{
  "mcpServers": {
    "hermify-team-brain": {
      "url": "https://YOUR_USERNAME-hermify-team-brain.hf.space/mcp"
    }
  }
}
```
*Note: FastMCP's HTTP transport automatically handles the `/mcp` or `/sse` routing based on the client's negotiation.*

---

## 🏗️ Architecture

`hermify-mcp` is built on a pluggable storage architecture, making it easy to scale or swap backends while maintaining a consistent MCP tool surface.

```text
src/hermify_mcp/
├── config.py           # HermifyConfig (Pydantic) + domain models
├── dataset_store.py    # Local-first DuckDB store (Skills, Memory, Audit Chain)
├── hf_sync.py          # Hugging Face Datasets sync engine (Parquet <-> Hub)
├── eval.py             # LLM-as-a-Judge evaluation pipeline (YOLO governance)
├── server.py           # FastMCP server - dataset-native tools
└── cli.py              # Typer CLI (hermify init/serve/sync)
```

### Governance & Approval Modes
Every skill write goes through a strict state machine (`draft` → `sandbox` → `active`).

| Mode | Behaviour |
|---|---|
| `human_review` | Skills stay `draft`. Humans review via HF Hub UI or CLI before promoting to `active`. |
| `yolo_eval` | An LLM-as-a-Judge automatically evaluates drafts. High-scoring skills auto-promote to `sandbox` (probationary use) or `active` (pure YOLO). |
| `local_only` | Skills and memory stay in the local DuckDB buffer. No network calls. Default for air-gapped environments. |

---

## 🛠️ CLI Reference

While agents interact with the server via MCP, you can manage your local brain directly from the terminal.

```bash
# Show help
uvx hermify-mcp --help

# Initialize / Reconfigure
uvx hermify-mcp init --home ~/.hermify --hf-repo user/repo --mode hf_push --yolo

# Manual Sync Operations (Useful for cron jobs or CI/CD)
uvx hermify-mcp sync push      # Force push local DuckDB to HF Hub
uvx hermify-mcp sync pull      # Pull latest Parquet shards from HF Hub
uvx hermify-mcp sync status    # View local buffer metrics and sync state

# Start server manually (defaults to stdio)
uvx hermify-mcp serve
uvx hermify-mcp serve --transport http --port 8742
```

---

## 🧰 MCP Tools Surface

### Skills & Governance
| Tool | Description |
|---|---|
| `propose_skill` | Append a new skill draft to the local dataset. Triggers YOLO eval if enabled. |
| `evaluate_skill` | Manually trigger the LLM Judge to score a draft and auto-transition state. |
| `approve_skill` | Human override to promote a `draft` or `sandbox` skill to `active`. |
| `search_skills` | Semantic or keyword search across the active dataset. |

### Core: hermify_log
```python
hermify_log(
  raw_transcript,   # full session text
  skill_md,         # pre-generated SKILL.md from reflective phase
  source_agent,     # "claude" | "gemini" | "hermes"
  session_id,
  task_goal,
)
```
Stores the log + creates a draft skill in the local buffer. One call = full hermification.

### Sync & Memory
| Tool | Description |
|---|---|
| `append_memory` | Append semantic memory to the local dataset buffer. |
| `get_memory` | Retrieve chronological memory entries for an agent. |
| `sync_status` | Show local buffer size, last sync timestamp, and HF Hub revision. |
| `sync_push` | Batch local DuckDB changes into Parquet and push to HF Hub. |
| `sync_pull` | Download latest Parquet shards from HF Hub and merge into local DB. |

---

## 🧩 Extensibility

The storage layer is abstracted. While DuckDB + Hugging Face Datasets is the default, the `BaseStore` protocol allows you to implement custom backends (e.g., PostgreSQL, LanceDB, or cloud object storage) without changing the MCP server interface.

Similarly, the `EvalJudge` protocol allows you to plug in any LLM (OpenAI, Anthropic, Ollama) for YOLO governance.

---

## 🤝 Contributing

We follow strict TDD. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting PRs.

```bash
# Clone and setup
git clone https://github.com/your-org/hermify-mcp.git
cd hermify-mcp
uv sync

# Run tests
uv run pytest

# Type checking
uv run mypy .
```

## License

MIT - see [LICENSE](LICENSE)
