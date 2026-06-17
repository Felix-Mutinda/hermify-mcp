"""Tests for hermify-mcp DatasetStore (Local DuckDB Buffer)."""

import pytest
from pathlib import Path
from hermify_mcp.config import HermifyConfig, SyncMode
from hermify_mcp.dataset_store import DatasetStore, GENESIS_HASH

# A trendy, universally relatable open-source AI skill
VALID_SKILL_MD = """\
---
name: unsloth-qlora-llama3-finetune
version: 0.1.0
description: Fine-tune a Llama-3 8B model using Unsloth and QLoRA for high-speed, low-memory instruction tuning.
tags: [llm, fine-tuning, qlora, unsloth, llama3, open-source]
author: ai-community
autonomy_level: L3
approval_gate: required
---
# Unsloth QLoRA Llama-3 Fine-Tuning

## When to Use
User wants to customize an open-weights LLM (like Llama-3) on a custom instruction dataset without requiring enterprise-grade GPU clusters.

## Procedure
1. Install dependencies: `pip install unsloth xformers trl peft accelerate bitsandbytes`
2. Load the base model in 4-bit precision using `FastLanguageModel.from_pretrained`.
3. Apply LoRA adapters targeting `q_proj`, `k_proj`, `v_proj`, `o_proj`.
4. Format the dataset using the model's specific chat template (e.g., Llama-3 instruct).
5. Train using `SFTTrainer` from `trl` for 1-3 epochs.
6. Save the merged model or export directly to GGUF for local inference.

## Pitfalls
- Do not use full 16-bit precision if VRAM is under 24GB; stick to 4-bit QLoRA.
- Ensure the dataset chat template exactly matches the base model, or the model will output garbage.
- Unsloth patches Triton; ensure your CUDA and PyTorch versions are compatible with the latest Unsloth release.

## Verification
- Check training loss curves for smooth convergence without spikes.
- Run a quick inference test using `vLLM` or `Ollama` on the exported GGUF to ensure the chat template renders correctly.
"""


@pytest.fixture
def store(tmp_path: Path):
    """Create a fresh DatasetStore backed by a temp DuckDB file."""
    cfg = HermifyConfig(hermify_home=tmp_path, sync_mode=SyncMode.LOCAL_ONLY)
    cfg.ensure_dirs()
    ds = DatasetStore(cfg)
    yield ds
    ds.close()


def test_init_creates_tables(store):
    """Ensure DuckDB tables are created on initialization."""
    tables = store._db.execute("SHOW TABLES").fetchall()
    table_names = [t[0] for t in tables]
    assert "skills" in table_names
    assert "memory" in table_names
    assert "audit_chain" in table_names


def test_propose_skill_creates_draft(store):
    """Proposing a skill should append a draft row with version 1."""
    result = store.propose_skill(VALID_SKILL_MD, agent_id="claude-1")
    assert result["status"] == "draft"
    assert result["version"] == 1
    assert result["skill_id"] == "unsloth-qlora-llama3-finetune"

    draft = store.get_skill("unsloth-qlora-llama3-finetune", status="draft")
    assert draft is not None
    assert "Unsloth QLoRA" in draft["content"]
    assert "llama3" in draft["tags"]


def test_approve_skill_appends_active_version(store):
    """Approving should append a NEW row with status=active, not mutate in place."""
    store.propose_skill(VALID_SKILL_MD, agent_id="claude-1")
    result = store.approve_skill(
        "unsloth-qlora-llama3-finetune", approved_by="human:admin"
    )

    assert result["status"] == "active"
    assert result["version"] == 2

    active = store.get_skill("unsloth-qlora-llama3-finetune", status="active")
    assert active is not None
    assert active["status"] == "active"
    assert active["approved_by"] == "human:admin"

    # Draft must still exist in history (append-only)
    drafts = store.list_skills(status="draft")
    assert len(drafts) == 1


def test_audit_hash_chain_integrity(store):
    """Each row's prev_hash must chain to the previous row's audit_hash."""
    store.propose_skill(VALID_SKILL_MD, agent_id="claude-1")
    store.approve_skill("unsloth-qlora-llama3-finetune", approved_by="human:admin")

    rows = store._db.execute("""
        SELECT audit_hash, prev_hash FROM skills
        WHERE skill_id = 'unsloth-qlora-llama3-finetune'
        ORDER BY version ASC
    """).fetchall()

    # First row chains to genesis
    assert rows[0][1] == GENESIS_HASH
    # Second row chains to first row's hash
    assert rows[1][1] == rows[0][0]


def test_search_skills_keyword(store):
    """Search should find active skills by keyword in content, tags, or description."""
    store.propose_skill(VALID_SKILL_MD, agent_id="claude-1")
    store.approve_skill("unsloth-qlora-llama3-finetune", approved_by="human")

    # Search by tag/keyword
    results = store.search_skills("qlora", limit=5)
    assert len(results) == 1
    assert results[0]["skill_id"] == "unsloth-qlora-llama3-finetune"

    # Search by content
    results_content = store.search_skills("Unsloth", limit=5)
    assert len(results_content) == 1

    # Test non-matching query
    assert len(store.search_skills("nonexistent-xyz")) == 0


def test_append_and_get_memory(store):
    """Memory should be appended chronologically and retrieved in order."""
    store.append_memory(
        "agent-1", "User prefers Python over JS for ML tasks.", session_id="sess-1"
    )
    store.append_memory(
        "agent-1", "Project uses PyTorch and Hugging Face.", session_id="sess-2"
    )

    mem = store.get_memory("agent-1")
    assert len(mem) == 2
    assert "Python over JS" in mem[0]["content"]
    assert "PyTorch" in mem[1]["content"]
    assert mem[0]["session_id"] == "sess-1"
