"""
config.py — Pydantic config + domain models for hermify-mcp (Dataset-backed).
"""

from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator, field_validator


class SyncMode(str, Enum):
    """Synchronization modes for the hermify-mcp storage layer."""

    LOCAL_ONLY = "local_only"  # Strictly local DuckDB, no network calls
    HF_MANUAL = "hf_manual"  # Local DuckDB, user triggers `sync_push` to HF Hub
    HF_PUSH = "hf_push"  # Local DuckDB, background/auto push to HF Hub


class ApprovalMode(str, Enum):
    """Governance modes for skill promotion."""

    HUMAN_REVIEW = "human_review"  # Strict human-in-the-loop (default)
    YOLO_EVAL = (
        "yolo_eval"  # Auto-evaluate via LLM Judge, promote to 'sandbox' or 'active'
    )


class AutonomyLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class HermifyConfig(BaseModel):
    """Core configuration for hermify-mcp."""

    hermify_home: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("HERMIFY_HOME", str(Path.home() / ".hermify"))
        ),
        description="Base directory for local hermify state (DuckDB, logs, config).",
    )

    # --- Storage & Sync ---
    sync_mode: SyncMode = Field(default=SyncMode.LOCAL_ONLY)
    hf_repo_id: Optional[str] = Field(
        default=None,
        description="Hugging Face Dataset repository ID (e.g., 'username/hermify-memory').",
    )
    hf_token: Optional[str] = Field(
        default=None,
        description="Hugging Face API token (reads from HF_TOKEN env var if not provided).",
    )

    # --- Governance & Eval ---
    approval_mode: ApprovalMode = Field(default=ApprovalMode.HUMAN_REVIEW)
    yolo_mode: bool = Field(
        default=False,
        description="Legacy alias for approval_mode == YOLO_EVAL. If true, enables auto-eval.",
    )
    eval_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum score required from LLM Judge to auto-promote a skill.",
    )

    # --- Core Settings ---
    agent_id: str = Field(default="hermify-agent")
    audit_log_enabled: bool = True
    audit_hash_chain: bool = True

    # --- Derived Paths ---
    db_path: Optional[Path] = Field(default=None, description="Local DuckDB file path.")
    audit_log_path: Optional[Path] = Field(
        default=None, description="Local audit log path."
    )

    @field_validator("hf_repo_id")
    @classmethod
    def validate_hf_repo_id(cls, v: Optional[str]) -> Optional[str]:
        """Ensure HF repo ID matches 'namespace/repo-name' format."""
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$", v):
            raise ValueError("hf_repo_id must be in the format 'namespace/repo-name'")
        return v

    @model_validator(mode="after")
    def _derive_paths_and_normalize(self) -> "HermifyConfig":
        base = self.hermify_home

        # Derive paths
        if self.db_path is None:
            self.db_path = base / "hermify.db"
        if self.audit_log_path is None:
            self.audit_log_path = base / "logs" / "audit.jsonl"

        # Normalize yolo_mode to approval_mode for backward compatibility / ease of use
        if self.yolo_mode and self.approval_mode == ApprovalMode.HUMAN_REVIEW:
            self.approval_mode = ApprovalMode.YOLO_EVAL

        # Default HF token from env if not set
        if self.hf_token is None:
            self.hf_token = os.environ.get("HF_TOKEN")

        return self

    def ensure_dirs(self) -> None:
        """Create necessary local directories."""
        if self.audit_log_path:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        # Note: DuckDB creates its own file, no dir needed for db_path itself

    @classmethod
    def load(cls, path: Path | None = None) -> "HermifyConfig":
        """Load configuration from a YAML file."""
        config_path = path or Path(
            os.environ.get(
                "HERMIFY_CONFIG", str(Path.home() / ".hermify" / "config.yaml")
            )
        )
        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text())
            return cls.model_validate(raw or {})
        return cls()

    def save(self, path: Path | None = None) -> None:
        """Save configuration to a YAML file."""
        config_path = path or (self.hermify_home / "config.yaml")
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Exclude None values and defaults to keep config clean
        dump_data = self.model_dump(
            mode="json", exclude_none=True, exclude_defaults=True
        )
        config_path.write_text(yaml.dump(dump_data, default_flow_style=False))


# --- Domain Models (Schemas for Dataset Rows) ---


class SkillFrontmatter(BaseModel):
    """Parsed frontmatter for a skill, mapped to dataset columns."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    author: str = "hermify"
    autonomy_level: AutonomyLevel = AutonomyLevel.L2
    approval_gate: Literal["required", "recommended", "optional"] = "required"
    derived_from_session: str | None = None
    derived_from_agent: str | None = None
    platforms: list[str] = Field(default_factory=list)
    related_skills: list[str] = Field(default_factory=list)


class SyncResult(BaseModel):
    """Result of a sync operation (push/pull)."""

    success: bool
    mode: SyncMode
    rows_synced: int = 0
    message: str = ""
    error: str | None = None
