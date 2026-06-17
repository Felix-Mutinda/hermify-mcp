"""
server.py — FastMCP server exposing hermify-mcp dataset-native tools.
Transport: stdio (default) or http.
Non-intrusive by design: Tools are called post-session, never injected
into the agent's reasoning loop.
"""

from __future__ import annotations

import logging
from typing import Optional, Literal

from fastmcp import FastMCP

from .config import HermifyConfig, ApprovalMode, SyncResult
from .dataset_store import DatasetStore
from .hf_sync import HFSyncEngine
from .eval import EvalJudge, PassThroughJudge

logger = logging.getLogger(__name__)


def create_server(
    config: HermifyConfig | None = None, eval_judge: EvalJudge | None = None
) -> FastMCP:
    """Factory to create and configure the FastMCP server."""
    cfg = config or HermifyConfig.load()
    cfg.ensure_dirs()

    store = DatasetStore(cfg)
    sync_engine = HFSyncEngine(store, cfg)

    # Fallback to PassThroughJudge if YOLO is on but no judge is provided
    judge = eval_judge or PassThroughJudge()

    mcp = FastMCP(
        name="hermify-mcp",
        version="0.2.0",
        instructions=(
            "Cross-agent skill & memory sync. Hermify agent interactions "
            "into dataset-backed artifacts. Supports Claude, Gemini, and "
            "any MCP-compatible runtime."
        ),
    )

    # -----------------------------------------------------------------------
    # SKILLS & GOVERNANCE
    # -----------------------------------------------------------------------

    @mcp.tool()
    def propose_skill(skill_md: str, agent_id: str) -> dict:
        """
        Propose a new skill draft.
        If YOLO_EVAL mode is enabled, automatically evaluates and promotes
        the skill if it passes the configured threshold.
        """
        try:
            # 1. Write to local buffer as draft
            draft_result = store.propose_skill(skill_md, agent_id=agent_id)
            skill_id = draft_result["skill_id"]

            final_status = "draft"
            eval_score = None
            approved_by = None

            # 2. YOLO Governance Pipeline
            if cfg.approval_mode == ApprovalMode.YOLO_EVAL:
                score = judge.evaluate(skill_md)
                eval_score = score

                if score >= cfg.eval_threshold:
                    # Auto-promote to active
                    approve_result = store.approve_skill(
                        skill_id,
                        approved_by=f"eval:{getattr(judge, 'name', 'unknown-judge')}",
                    )
                    final_status = approve_result["status"]
                    approved_by = approve_result.get("approved_by")
                    logger.info(f"YOLO: Auto-approved '{skill_id}' with score {score}")
                else:
                    logger.info(f"YOLO: Rejected '{skill_id}' with score {score}")

            return {
                "success": True,
                "skill_id": skill_id,
                "status": final_status,
                "eval_score": eval_score,
                "approved_by": approved_by,
                "message": f"Skill '{skill_id}' proposed as {final_status}.",
            }
        except Exception as e:
            logger.error(f"Failed to propose skill: {e}")
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def approve_skill(skill_id: str, approved_by: str = "human") -> dict:
        """Human override: Promote a draft or sandbox skill to active."""
        try:
            result = store.approve_skill(skill_id, approved_by=approved_by)
            return {"success": True, **result}
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def list_skills(status: Optional[str] = None) -> dict:
        """List skills, optionally filtered by status (e.g., 'active', 'draft')."""
        skills = store.list_skills(status=status)
        return {
            "total": len(skills),
            "skills": [
                {
                    "skill_id": s["skill_id"],
                    "status": s["status"],
                    "version": s["version"],
                    "description": s["description"],
                    "tags": s["tags"],
                }
                for s in skills
            ],
        }

    @mcp.tool()
    def get_skill(skill_id: str, status: str = "active") -> dict:
        """Retrieve the full content of a specific skill version."""
        skill = store.get_skill(skill_id, status=status)
        if not skill:
            return {
                "found": False,
                "error": f"Skill '{skill_id}' not found with status '{status}'",
            }
        return {"found": True, **skill}

    @mcp.tool()
    def search_skills(query: str, limit: int = 5) -> dict:
        """Keyword search across active skills."""
        matches = store.search_skills(query, limit=limit)
        return {"query": query, "total": len(matches), "matches": matches}

    # -----------------------------------------------------------------------
    # MEMORY
    # -----------------------------------------------------------------------

    @mcp.tool()
    def append_memory(
        content: str, agent_id: str, session_id: Optional[str] = None
    ) -> dict:
        """Append a semantic memory entry to the local dataset buffer."""
        try:
            result = store.append_memory(agent_id, content, session_id=session_id)
            return {"success": True, **result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @mcp.tool()
    def get_memory(agent_id: str) -> dict:
        """Retrieve chronological memory entries for an agent."""
        entries = store.get_memory(agent_id)
        return {"agent_id": agent_id, "total": len(entries), "entries": entries}

    # -----------------------------------------------------------------------
    # SYNC ENGINE
    # -----------------------------------------------------------------------

    @mcp.tool()
    def sync_status() -> dict:
        """Get local buffer metrics and sync configuration."""
        return sync_engine.status()

    @mcp.tool()
    def sync_push() -> dict:
        """Batch local DuckDB changes into Parquet and push to Hugging Face Hub."""
        result: SyncResult = sync_engine.push()
        return result.model_dump()

    @mcp.tool()
    def sync_pull() -> dict:
        """Download latest Parquet shards from HF Hub and merge into local DB."""
        result: SyncResult = sync_engine.pull()
        return result.model_dump()

    return mcp


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = HermifyConfig.load()
    server = create_server(cfg)

    # Run via stdio for Claude Desktop / Gemini CLI, or HTTP for team deployments
    transport: Literal["stdio", "http", "sse", "streamable-http"] = (
        "http" if cfg.http_mode else "stdio"
    )
    server.run(transport=transport, host="0.0.0.0", port=8742)


if __name__ == "__main__":
    main()
