
# Contributing to hermify-mcp

Welcome! We're building the future of cross-agent memory and skill sharing. This guide will help you get set up and understand our architectural principles.

## 🛠️ Development Setup

We use [`uv`](https://github.com/astral-sh/uv) for lightning-fast dependency management and Python versioning.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/hermify-mcp.git
   cd hermify-mcp
   ```

2. **Install dependencies and set up the environment:**
   ```bash
   uv sync
   ```

3. **Run the test suite to verify your setup:**
   ```bash
   uv run pytest
   ```

## 🏗️ Architectural Principles

Before writing code, please internalize these core design pillars:

1. **Local-First, Dataset-Backed**: All MCP tool writes MUST go to the local DuckDB buffer first. Network calls to Hugging Face Hub are strictly asynchronous (handled by `sync_push`). The agent loop must never block on I/O.
2. **Event-Sourced Immutability**: Skills and memory are not "updated" in place. State changes (e.g., `draft` → `active`) are handled by appending new rows with incremented versions or status flags. 
3. **Extensible Storage**: The `DatasetStore` should implement a clear interface. If you are adding a new storage backend, ensure it adheres to the same ACID and audit-chain guarantees as the DuckDB implementation.

## 🧪 Test-Driven Development (TDD) Workflow

We strictly follow TDD. **Do not submit a PR without tests.**

1. **Write the test first**: Define the expected behavior in `tests/`. Mock external dependencies (like the HF Hub API or LLM Judge).
   ```python
   def test_propose_skill_creates_draft(store):
       skill_md = "name: test\n---\nBody"
       result = store.propose_skill(skill_md, agent_id="agent-1")
       assert result['status'] == 'draft'
   ```
2. **Watch it fail**: Run `uv run pytest tests/test_dataset_store.py::test_propose_skill_creates_draft`.
3. **Write the minimal code**: Implement the feature in `src/hermify_mcp/` to make the test pass.
4. **Refactor**: Clean up the code while keeping the test green.

## 📝 Code Quality & Linting

We enforce strict code quality standards. Before pushing, run:

```bash
# Format and lint
uv run ruff format .
uv run ruff check . --fix

# Type checking
uv run mypy src/hermify_mcp
```

## 🚀 Pull Request Process

1. Create a feature branch: `git checkout -b feat/your-feature-name`
2. Ensure all tests pass: `uv run pytest`
3. Ensure linting and typing pass.
4. Open a Pull Request with a clear description of the problem solved and how the TDD approach was applied.
5. A maintainer will review, focusing on architectural alignment and test coverage.

## 💡 Questions?

Open an issue or start a discussion in the GitHub repo. We're happy to help you navigate the codebase!
