"""
dataset_store.py — Local-first DuckDB buffer for hermify-mcp.
Handles append-only state transitions, SHA-256 audit chaining,
and tabular skill/memory management before async sync to HF Hub.
"""

from __future__ import annotations

import duckdb
import hashlib
import logging
import re
import yaml
from datetime import datetime, timezone
from typing import Optional

from .config import HermifyConfig, SkillFrontmatter

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class DatasetStore:
    """Local transactional buffer backed by DuckDB."""

    def __init__(self, config: HermifyConfig):
        self.cfg = config
        self.cfg.ensure_dirs()
        self._db = duckdb.connect(str(self.cfg.db_path))
        self._init_schema()

    def _init_schema(self):
        """Create append-only tables with hash-chain support."""
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS skills (
                skill_id VARCHAR,
                version INTEGER,
                status VARCHAR,
                content TEXT,
                tags VARCHAR[],
                description VARCHAR,
                autonomy_level VARCHAR,
                eval_score FLOAT,
                approved_by VARCHAR,
                prev_hash VARCHAR(64),
                audit_hash VARCHAR(64) PRIMARY KEY,
                timestamp TIMESTAMP
            )
        """)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                agent_id VARCHAR,
                memory_type VARCHAR,
                content TEXT,
                session_id VARCHAR,
                prev_hash VARCHAR(64),
                audit_hash VARCHAR(64) PRIMARY KEY,
                timestamp TIMESTAMP
            )
        """)
        # Lightweight audit trail table (optional, mirrors hash chain)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS audit_chain (
                row_hash VARCHAR(64),
                table_name VARCHAR,
                row_id VARCHAR,
                timestamp TIMESTAMP
            )
        """)

    def close(self):
        """Gracefully close DuckDB connection."""
        if self._db:
            self._db.close()

    def _calculate_hash(self, content: str, prev_hash: str, timestamp: str) -> str:
        """Compute SHA-256 chain hash."""
        payload = f"{prev_hash}:{content}:{timestamp}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def _get_latest_hash(
        self, table: str, skill_id: Optional[str] = None, agent_id: Optional[str] = None
    ) -> str:
        """Retrieve the most recent audit_hash for chaining."""
        if table == "skills" and skill_id:
            res = self._db.execute(
                """
                SELECT audit_hash FROM skills
                WHERE skill_id = ? ORDER BY version DESC LIMIT 1
            """,
                [skill_id],
            ).fetchone()
        elif table == "memory" and agent_id:
            res = self._db.execute(
                """
                SELECT audit_hash FROM memory
                WHERE agent_id = ? ORDER BY timestamp DESC LIMIT 1
            """,
                [agent_id],
            ).fetchone()
        else:
            res = None
        return res[0] if res else GENESIS_HASH

    def _parse_skill_md(self, skill_md: str) -> tuple[str, SkillFrontmatter]:
        """Robustly parse YAML frontmatter from SKILL.md."""
        # Standard --- delimited
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", skill_md, re.DOTALL)
        if match:
            yaml_str, body = match.groups()
        else:
            # Fallback: treat leading key-value lines as frontmatter
            lines = skill_md.split("\n")
            yaml_lines, body_lines = [], []
            in_frontmatter = True
            for line in lines:
                if in_frontmatter and (
                    line.strip() == "" or not re.match(r"^\w+:", line)
                ):
                    in_frontmatter = False
                if in_frontmatter:
                    yaml_lines.append(line)
                else:
                    body_lines.append(line)
            yaml_str, _body = "\n".join(yaml_lines), "\n".join(body_lines)

        fm_data = yaml.safe_load(yaml_str) or {}
        fm = SkillFrontmatter(**fm_data)
        return skill_md, fm

    # ─────────────────────────────────────────────────────────────
    # SKILL OPERATIONS
    # ─────────────────────────────────────────────────────────────

    def propose_skill(self, skill_md: str, agent_id: str) -> dict:
        """Append a new skill draft to the local buffer."""
        _, fm = self._parse_skill_md(skill_md)
        skill_id = fm.name
        ts = datetime.now(timezone.utc).isoformat()
        version = 1
        prev_hash = self._get_latest_hash("skills", skill_id)
        audit_hash = self._calculate_hash(skill_md, prev_hash, ts)

        self._db.execute(
            """
            INSERT INTO skills (
                skill_id, version, status, content, tags, description,
                autonomy_level, eval_score, approved_by, prev_hash, audit_hash, timestamp
            ) VALUES (?, ?, 'draft', ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
            [
                skill_id,
                version,
                skill_md,
                fm.tags,
                fm.description,
                fm.autonomy_level.value,
                agent_id,
                prev_hash,
                audit_hash,
                ts,
            ],
        )

        logger.info(f"Proposed draft skill '{skill_id}' v{version}")
        return {
            "skill_id": skill_id,
            "version": version,
            "status": "draft",
            "audit_hash": audit_hash,
        }

    def get_skill(self, skill_id: str, status: str = "active") -> Optional[dict]:
        """Retrieve the latest version of a skill with a specific status."""
        res = self._db.execute(
            """
            SELECT * FROM skills
            WHERE skill_id = ? AND status = ?
            ORDER BY version DESC LIMIT 1
        """,
            [skill_id, status],
        ).fetchone()

        if not res:
            return None

        cols = [
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
        ]
        return dict(zip(cols, res))

    def list_skills(self, status: Optional[str] = None) -> list[dict]:
        """List latest versions of skills, optionally filtered by status."""
        if status:
            query = """
                SELECT s1.* FROM skills s1
                INNER JOIN (
                    SELECT skill_id, MAX(version) as max_ver
                    FROM skills WHERE status = ?
                    GROUP BY skill_id
                ) s2 ON s1.skill_id = s2.skill_id AND s1.version = s2.max_ver
                WHERE s1.status = ?
                ORDER BY s1.timestamp DESC
            """
            params = [status, status]
        else:
            query = """
                SELECT s1.* FROM skills s1
                INNER JOIN (
                    SELECT skill_id, MAX(version) as max_ver
                    FROM skills GROUP BY skill_id
                ) s2 ON s1.skill_id = s2.skill_id AND s1.version = s2.max_ver
                ORDER BY s1.timestamp DESC
            """
            params = []

        res = self._db.execute(query, params).fetchall()
        cols = [
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
        ]
        return [dict(zip(cols, row)) for row in res]

    def approve_skill(self, skill_id: str, approved_by: str = "human") -> dict:
        """Promote a draft to active by appending a new versioned row."""
        draft = self.get_skill(skill_id, status="draft")
        if not draft:
            raise FileNotFoundError(f"No draft found for skill '{skill_id}'")

        ts = datetime.now(timezone.utc).isoformat()
        version = draft["version"] + 1
        prev_hash = draft["audit_hash"]
        audit_hash = self._calculate_hash(draft["content"], prev_hash, ts)

        self._db.execute(
            """
            INSERT INTO skills (
                skill_id, version, status, content, tags, description,
                autonomy_level, eval_score, approved_by, prev_hash, audit_hash, timestamp
            ) VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                skill_id,
                version,
                draft["content"],
                draft["tags"],
                draft["description"],
                draft["autonomy_level"],
                draft.get("eval_score"),
                approved_by,
                prev_hash,
                audit_hash,
                ts,
            ],
        )

        logger.info(f"Approved skill '{skill_id}' v{version} by {approved_by}")
        return {
            "skill_id": skill_id,
            "version": version,
            "status": "active",
            "audit_hash": audit_hash,
        }

    def search_skills(self, query: str, limit: int = 5) -> list[dict]:
        """Keyword search across active skills."""
        res = self._db.execute(
            """
            SELECT skill_id, status, version, description, tags, autonomy_level
            FROM skills
            WHERE status = 'active' AND (
                LOWER(content) LIKE LOWER(?) OR
                LOWER(description) LIKE LOWER(?) OR
                array_to_string(tags, ' ') ILIKE ?
            )
            ORDER BY version DESC
            LIMIT ?
        """,
            [f"%{query}%", f"%{query}%", f"%{query}%", limit],
        ).fetchall()

        cols = [
            "skill_id",
            "status",
            "version",
            "description",
            "tags",
            "autonomy_level",
        ]
        return [dict(zip(cols, row)) for row in res]

    # ─────────────────────────────────────────────────────────────
    # MEMORY OPERATIONS
    # ─────────────────────────────────────────────────────────────

    def append_memory(
        self,
        agent_id: str,
        content: str,
        session_id: Optional[str] = None,
        memory_type: str = "semantic",
    ) -> dict:
        """Append a memory entry to the local buffer."""
        ts = datetime.now(timezone.utc).isoformat()
        prev_hash = self._get_latest_hash("memory", agent_id=agent_id)
        audit_hash = self._calculate_hash(content, prev_hash, ts)

        self._db.execute(
            """
            INSERT INTO memory (agent_id, memory_type, content, session_id, prev_hash, audit_hash, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            [agent_id, memory_type, content, session_id, prev_hash, audit_hash, ts],
        )

        return {"agent_id": agent_id, "audit_hash": audit_hash, "timestamp": ts}

    def get_memory(self, agent_id: str) -> list[dict]:
        """Retrieve chronological memory entries for an agent."""
        res = self._db.execute(
            """
            SELECT * FROM memory WHERE agent_id = ? ORDER BY timestamp ASC
        """,
            [agent_id],
        ).fetchall()
        cols = [
            "agent_id",
            "memory_type",
            "content",
            "session_id",
            "prev_hash",
            "audit_hash",
            "timestamp",
        ]
        return [dict(zip(cols, row)) for row in res]
