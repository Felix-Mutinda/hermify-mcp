"""Tests for hermify-mcp Hugging Face Sync Engine."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datasets import Dataset  # type: ignore[import-untyped]

from hermify_mcp.config import HermifyConfig, SyncMode
from hermify_mcp.dataset_store import DatasetStore
from hermify_mcp.hf_sync import HFSyncEngine

VALID_SKILL_MD = """\
---
name: unsloth-qlora-llama3-finetune
version: 0.1.0
description: Fine-tune Llama-3 using Unsloth.
tags: [llm, qlora]
author: test
autonomy_level: L3
approval_gate: required
---
# Unsloth QLoRA
When to Use: Fine-tuning.
"""


@pytest.fixture
def store(tmp_path: Path):
    cfg = HermifyConfig(hermify_home=tmp_path, sync_mode=SyncMode.LOCAL_ONLY)
    cfg.ensure_dirs()
    ds = DatasetStore(cfg)
    yield ds
    ds.close()


@pytest.fixture
def hf_engine(store):
    cfg = HermifyConfig(
        hermify_home=store.cfg.hermify_home,
        sync_mode=SyncMode.HF_PUSH,
        hf_repo_id="test-user/hermify-memory",  # Base repo ID
        hf_token="fake_token_123",
    )
    return HFSyncEngine(store, cfg)


def test_local_only_mode_is_noop(store):
    """If mode is LOCAL_ONLY, sync engine should do nothing."""
    cfg_local = HermifyConfig(
        hermify_home=store.cfg.hermify_home, sync_mode=SyncMode.LOCAL_ONLY
    )
    engine = HFSyncEngine(store, cfg_local)

    result = engine.push()
    assert result.success is True
    assert result.rows_synced == 0
    assert "Local-only" in result.message


def test_push_converts_duckdb_to_dataset_and_pushes(hf_engine, store):
    """Push should read from DuckDB, create Datasets, and push to SEPARATE repos."""
    # 1. Seed local DB
    store.propose_skill(VALID_SKILL_MD, agent_id="claude-1")
    store.append_memory("agent-1", "User likes Python.", session_id="sess-1")

    # 2. Mock the HF push mechanism
    with patch("datasets.Dataset.push_to_hub") as mock_push:
        mock_push.return_value = MagicMock()

        result = hf_engine.push()

        # 3. Verify assertions
        assert result.success is True
        assert result.rows_synced > 0

        # Verify push_to_hub was called TWICE (once for skills, once for memory)
        assert mock_push.call_count == 2

        # Verify the correct separate repos were targeted
        calls = mock_push.call_args_list
        repos_called = {call.kwargs["repo_id"] for call in calls}
        assert "test-user/hermify-memory-skills" in repos_called
        assert "test-user/hermify-memory-memory" in repos_called


def test_pull_merges_remote_data_without_duplicates(hf_engine, store):
    """Pull should download from HF and insert into DuckDB, ignoring existing hashes."""
    # 1. Seed local DB with one memory entry
    local_mem = store.append_memory("agent-1", "Local memory.", session_id="sess-1")

    # 2. Mock remote data
    mock_remote_data = {
        "agent_id": ["agent-1", "agent-2"],
        "memory_type": ["semantic", "semantic"],
        "content": ["Local memory.", "Remote memory from Gemini."],
        "session_id": ["sess-1", "sess-2"],
        "prev_hash": ["0" * 64, "1" * 64],
        "audit_hash": [local_mem["audit_hash"], "2" * 64],
        "timestamp": ["2024-01-01T00:00:00", "2024-01-02T00:00:00"],
    }
    mock_memory_dataset = Dataset.from_dict(mock_remote_data)

    # 3. Mock load_dataset to return specific datasets based on the repo ID
    def mock_load_dataset(repo_id, *args, **kwargs):
        if "skills" in repo_id:
            return Dataset.from_dict({})  # Empty skills dataset
        elif "memory" in repo_id:
            return mock_memory_dataset
        raise ValueError(f"Unexpected repo: {repo_id}")

    with patch("hermify_mcp.hf_sync.load_dataset", side_effect=mock_load_dataset):
        result = hf_engine.pull()

        assert result.success is True
        assert result.rows_synced == 1  # Only the new remote memory row

        # 4. Verify local DB state
        gemini_mem = store.get_memory("agent-2")
        assert len(gemini_mem) == 1
        assert gemini_mem[0]["content"] == "Remote memory from Gemini."
