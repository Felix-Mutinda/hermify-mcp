"""
hf_sync.py — Hugging Face Datasets sync engine for hermify-mcp.
Bridges the local DuckDB transactional buffer with the immutable
Hugging Face Hub (Parquet shards).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from datasets import Dataset, load_dataset  # type: ignore[import-untyped]
from huggingface_hub import HfApi

from .config import HermifyConfig, SyncMode, SyncResult

if TYPE_CHECKING:
    from .dataset_store import DatasetStore

logger = logging.getLogger(__name__)


class HFSyncEngine:
    """Handles bidirectional sync between local DuckDB and HF Hub."""

    def __init__(self, store: "DatasetStore", config: HermifyConfig):
        self.store = store
        self.cfg = config
        self.api = HfApi()

    def push(self) -> SyncResult:
        """Push local DuckDB state to Hugging Face Hub."""
        if self.cfg.sync_mode == SyncMode.LOCAL_ONLY:
            return SyncResult(
                success=True,
                mode=self.cfg.sync_mode,
                message="Local-only mode; push skipped.",
            )

        if not self.cfg.hf_repo_id:
            return SyncResult(
                success=False,
                mode=self.cfg.sync_mode,
                error="hf_repo_id is not configured.",
            )

        try:
            # 1. Extract data from DuckDB
            skills_rows = self.store._db.execute("SELECT * FROM skills").fetchall()
            memory_rows = self.store._db.execute("SELECT * FROM memory").fetchall()

            # 2. Convert to HF Datasets
            skills_ds = self._rows_to_dataset(
                skills_rows,
                [
                    "skill_id",
                    "version",
                    "status",
                    "content",
                    "tags",
                    "description",
                    "autonomy_level",
                    "eval_score",
                    "approved_by",
                    "prev_hash",
                    "audit_hash",
                    "timestamp",
                ],
            )

            memory_ds = self._rows_to_dataset(
                memory_rows,
                [
                    "agent_id",
                    "memory_type",
                    "content",
                    "session_id",
                    "prev_hash",
                    "audit_hash",
                    "timestamp",
                ],
            )

            # 3. Push to Hub (Separate repos required because HF Hub enforces 1 schema per repo)
            skills_repo = f"{self.cfg.hf_repo_id}-skills"
            memory_repo = f"{self.cfg.hf_repo_id}-memory"

            skills_ds.push_to_hub(
                repo_id=skills_repo, token=self.cfg.hf_token, private=True
            )
            memory_ds.push_to_hub(
                repo_id=memory_repo, token=self.cfg.hf_token, private=True
            )

            total_rows = len(skills_rows) + len(memory_rows)
            logger.info(
                f"Successfully pushed {total_rows} rows to {skills_repo} and {memory_repo}"
            )

            return SyncResult(
                success=True,
                mode=self.cfg.sync_mode,
                rows_synced=total_rows,
                message=f"Pushed {total_rows} rows to HF Hub",
            )

        except Exception as e:
            logger.error(f"Failed to push to HF Hub: {e}")
            return SyncResult(success=False, mode=self.cfg.sync_mode, error=str(e))

    def pull(self) -> SyncResult:
        """Pull latest state from Hugging Face Hub and merge into local DuckDB."""
        if self.cfg.sync_mode == SyncMode.LOCAL_ONLY:
            return SyncResult(
                success=True,
                mode=self.cfg.sync_mode,
                message="Local-only mode; pull skipped.",
            )

        if not self.cfg.hf_repo_id:
            return SyncResult(
                success=False,
                mode=self.cfg.sync_mode,
                error="hf_repo_id is not configured.",
            )

        try:
            skills_repo = f"{self.cfg.hf_repo_id}-skills"
            memory_repo = f"{self.cfg.hf_repo_id}-memory"
            rows_synced = 0

            # 1. Pull Skills
            try:
                skills_ds = load_dataset(
                    skills_repo, token=self.cfg.hf_token, split="train"
                )
                if skills_ds:
                    rows_synced += self._merge_skills(skills_ds)
            except Exception as e:
                logger.warning(f"Could not load skills from {skills_repo}: {e}")

            # 2. Pull Memory
            try:
                memory_ds = load_dataset(
                    memory_repo, token=self.cfg.hf_token, split="train"
                )
                if memory_ds:
                    rows_synced += self._merge_memory(memory_ds)
            except Exception as e:
                logger.warning(f"Could not load memory from {memory_repo}: {e}")

            logger.info(
                f"Successfully pulled and merged {rows_synced} new rows from HF Hub"
            )

            return SyncResult(
                success=True,
                mode=self.cfg.sync_mode,
                rows_synced=rows_synced,
                message=f"Pulled {rows_synced} new rows from HF Hub",
            )

        except Exception as e:
            logger.error(f"Failed to pull from HF Hub: {e}")
            return SyncResult(success=False, mode=self.cfg.sync_mode, error=str(e))

    def _rows_to_dataset(self, rows: list[tuple], columns: list[str]) -> Dataset:
        """Convert DuckDB fetchall() tuples into a Hugging Face Dataset."""
        if not rows:
            return Dataset.from_dict({col: [] for col in columns})

        # Explicitly annotate the dictionary type
        data_dict: dict[str, list[Any]] = {col: [] for col in columns}
        for row in rows:
            for i, col in enumerate(columns):
                val = row[i]
                if isinstance(val, tuple):
                    val = list(val)
                data_dict[col].append(val)

        return Dataset.from_dict(data_dict)

    def _merge_skills(self, remote_ds: Dataset) -> int:
        """Insert remote skills into local DB, ignoring existing audit_hashes."""
        count = 0
        for row in remote_ds:
            exists = self.store._db.execute(
                "SELECT 1 FROM skills WHERE audit_hash = ?", [row["audit_hash"]]
            ).fetchone()

            if not exists:
                self.store._db.execute(
                    """
                    INSERT INTO skills (
                        skill_id, version, status, content, tags, description,
                        autonomy_level, eval_score, approved_by, prev_hash, audit_hash, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        row["skill_id"],
                        row["version"],
                        row["status"],
                        row["content"],
                        row["tags"],
                        row["description"],
                        row["autonomy_level"],
                        row["eval_score"],
                        row["approved_by"],
                        row["prev_hash"],
                        row["audit_hash"],
                        row["timestamp"],
                    ],
                )
                count += 1
        return count

    def _merge_memory(self, remote_ds: Dataset) -> int:
        """Insert remote memory into local DB, ignoring existing audit_hashes."""
        count = 0
        for row in remote_ds:
            exists = self.store._db.execute(
                "SELECT 1 FROM memory WHERE audit_hash = ?", [row["audit_hash"]]
            ).fetchone()

            if not exists:
                self.store._db.execute(
                    """
                    INSERT INTO memory (agent_id, memory_type, content, session_id, prev_hash, audit_hash, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        row["agent_id"],
                        row["memory_type"],
                        row["content"],
                        row["session_id"],
                        row["prev_hash"],
                        row["audit_hash"],
                        row["timestamp"],
                    ],
                )
                count += 1
        return count

    def status(self) -> dict:
        """Get sync status without performing network calls."""
        # Safely fetch and unpack the counts
        skills_row = self.store._db.execute("SELECT COUNT(*) FROM skills").fetchone()
        memory_row = self.store._db.execute("SELECT COUNT(*) FROM memory").fetchone()

        local_skills = skills_row[0] if skills_row else 0
        local_memory = memory_row[0] if memory_row else 0

        return {
            "mode": self.cfg.sync_mode.value,
            "hf_repo_id": self.cfg.hf_repo_id,
            "local_buffer": {"skills": local_skills, "memory": local_memory},
        }
