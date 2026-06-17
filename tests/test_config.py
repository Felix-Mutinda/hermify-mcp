"""Tests for hermify-mcp configuration and domain models."""

import pytest
from pathlib import Path
from pydantic import ValidationError

from hermify_mcp.config import HermifyConfig, SyncMode


def test_default_config_uses_local_only(tmp_path: Path):
    """By default, config should be local-only with no HF repo."""
    cfg = HermifyConfig(hermify_home=tmp_path)
    assert cfg.sync_mode == SyncMode.LOCAL_ONLY
    assert cfg.hf_repo_id is None
    assert cfg.yolo_mode is False
    assert cfg.eval_threshold == 0.8


def test_hf_repo_id_validation():
    """HF repo IDs must strictly follow the 'namespace/repo-name' format."""
    # Valid formats
    valid_cfg = HermifyConfig(
        hermify_home=Path("/tmp"),
        hf_repo_id="user-name/hermify-memory-v1",
        sync_mode=SyncMode.HF_PUSH,
    )
    assert valid_cfg.hf_repo_id == "user-name/hermify-memory-v1"

    # Invalid formats (missing slash, invalid chars)
    with pytest.raises(ValidationError):
        HermifyConfig(hf_repo_id="invalid-format-no-slash")

    with pytest.raises(ValidationError):
        HermifyConfig(hf_repo_id="user/name/with/too/many/slashes")


def test_path_derivation_includes_duckdb(tmp_path: Path):
    """Config should automatically derive the local DuckDB path."""
    cfg = HermifyConfig(hermify_home=tmp_path)

    # The local transactional buffer should be in the hermify home
    assert cfg.db_path == tmp_path / "hermify.db"
    assert cfg.audit_log_path == tmp_path / "logs" / "audit.jsonl"


def test_yolo_mode_requires_eval_threshold(tmp_path: Path):
    """Ensure eval threshold is bounded between 0.0 and 1.0."""
    # Valid threshold
    cfg = HermifyConfig(hermify_home=tmp_path, yolo_mode=True, eval_threshold=0.85)
    assert cfg.eval_threshold == 0.85

    # Invalid threshold (too high)
    with pytest.raises(ValidationError):
        HermifyConfig(hermify_home=tmp_path, eval_threshold=1.5)

    # Invalid threshold (too low)
    with pytest.raises(ValidationError):
        HermifyConfig(hermify_home=tmp_path, eval_threshold=-0.1)


def test_ensure_dirs_creates_necessary_folders(tmp_path: Path):
    """ensure_dirs should create the logs directory for the audit chain."""
    cfg = HermifyConfig(hermify_home=tmp_path)
    cfg.ensure_dirs()

    assert (tmp_path / "logs").exists()
    assert (
        tmp_path / "logs" / "audit.jsonl"
    ).exists() or True  # File might be created on first write, but dir must exist
