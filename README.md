# hermify-mcp

> Cross-agent, dataset-backed skill and memory sync via MCP.
> Hermify your agent interactions — push from Claude, pull into Gemini, improve without friction.

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

## Architecture

`hermify-mcp` is built on a pluggable storage architecture, making it easy to scale or swap backends while maintaining a consistent MCP tool surface.

```text
src/hermify_mcp/
├── config.py           # HermifyConfig (Pydantic) + domain models
├── dataset_store.py    # Local-first DuckDB store (Skills, Memory, Audit Chain)
├── hf_sync.py          # Hugging Face Datasets sync engine (Parquet <-> Hub)
├── server.py           # FastMCP server — dataset-native tools
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

## Quick start

```bash
# Install via uv (recommended)
uv pip install hermify-mcp

# Bootstrap (creates local DuckDB and configures HF Hub target)
hermify init --home ~/.hermify --hf-repo your-username/hermify-agent-memory --mode yolo_eval

# Start MCP server (stdio — for Claude Desktop, Gemini CLI, VS Code)
hermify serve
```

### Claude Desktop config (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "hermify": {
      "command": "hermify",
      "args": ["serve"]
    }
  }
}
```

---

## MCP Tools

### Skills & Governance
| Tool | Description |
|---|---|
| `propose_skill` | Append a new skill draft to the local dataset. |
| `evaluate_skill` | Trigger the LLM Judge to score a draft and auto-transition state. |
| `approve_skill` | Human override to promote a `draft` or `sandbox` skill to `active`. |
| `search_skills` | Semantic or keyword search across the local dataset. |

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

### Sync
| Tool | Description |
|---|---|
| `sync_status` | Show local buffer size, last sync timestamp, and HF Hub revision. |
| `sync_push` | Batch local DuckDB changes into Parquet and push to HF Hub. |
| `sync_pull` | Download latest Parquet shards from HF Hub and merge into local DB. |

---

## Extensibility

The storage layer is abstracted. While DuckDB + Hugging Face Datasets is the default, the `BaseStore` protocol allows you to implement custom backends (e.g., PostgreSQL, LanceDB, or cloud object storage) without changing the MCP server interface.

---

## License

MIT — see [LICENSE](LICENSE)
