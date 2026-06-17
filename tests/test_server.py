"""Tests for the hermify-mcp FastMCP Server and YOLO Governance."""

import pytest
import json
from pathlib import Path

from hermify_mcp.config import HermifyConfig, SyncMode, ApprovalMode
from hermify_mcp.eval import MockEvalJudge
from hermify_mcp.server import create_server

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
def human_review_server(tmp_path: Path):
    """Server configured for strict human-in-the-loop review."""
    cfg = HermifyConfig(
        hermify_home=tmp_path,
        sync_mode=SyncMode.LOCAL_ONLY,
        approval_mode=ApprovalMode.HUMAN_REVIEW,
    )
    cfg.ensure_dirs()
    return create_server(cfg)


@pytest.fixture
def yolo_server(tmp_path: Path):
    """Server configured for YOLO auto-approval with a high-scoring mock judge."""
    cfg = HermifyConfig(
        hermify_home=tmp_path,
        sync_mode=SyncMode.LOCAL_ONLY,
        approval_mode=ApprovalMode.YOLO_EVAL,
        eval_threshold=0.8,
    )
    cfg.ensure_dirs()
    judge = MockEvalJudge(score=0.95)
    return create_server(cfg, eval_judge=judge)


# Helper to safely extract JSON from MCP ToolResult
def extract_json(result_obj) -> dict:
    """Extracts and parses JSON from an MCP ToolResult/CallToolResult."""
    # Standard MCP SDK structure: result.content[0].text
    if hasattr(result_obj, "content") and len(result_obj.content) > 0:
        return json.loads(result_obj.content[0].text)
    # Fallback if the library uses a different attribute
    raise TypeError(
        f"Could not find text content in result object. Attributes: {dir(result_obj)}"
    )


@pytest.mark.asyncio
async def test_propose_skill_human_review(human_review_server):
    """In human review mode, proposing a skill must leave it in 'draft' status."""
    res = await human_review_server.call_tool(
        "propose_skill", {"skill_md": VALID_SKILL_MD, "agent_id": "claude-1"}
    )

    data = extract_json(res)
    assert data["success"] is True
    assert data["status"] == "draft"
    assert data["approved_by"] is None


@pytest.mark.asyncio
async def test_propose_skill_yolo_auto_approves(yolo_server):
    """In YOLO mode, a high-scoring skill must auto-promote to 'active'."""
    res = await yolo_server.call_tool(
        "propose_skill", {"skill_md": VALID_SKILL_MD, "agent_id": "claude-1"}
    )

    data = extract_json(res)
    assert data["success"] is True
    assert data["status"] == "active"
    assert data["eval_score"] == 0.95
    assert "mock-judge" in data["approved_by"]


@pytest.mark.asyncio
async def test_list_and_search_skills(yolo_server):
    """Ensure list and search tools correctly query the active dataset."""
    # 1. Propose and auto-approve via YOLO
    await yolo_server.call_tool(
        "propose_skill", {"skill_md": VALID_SKILL_MD, "agent_id": "claude-1"}
    )

    # 2. List active skills
    list_res = await yolo_server.call_tool("list_skills", {"status": "active"})
    list_data = extract_json(list_res)
    assert len(list_data["skills"]) == 1
    assert list_data["skills"][0]["skill_id"] == "unsloth-qlora-llama3-finetune"

    # 3. Search skills
    search_res = await yolo_server.call_tool("search_skills", {"query": "qlora"})
    search_data = extract_json(search_res)
    assert len(search_data["matches"]) == 1


@pytest.mark.asyncio
async def test_sync_status_tool(human_review_server):
    """Ensure sync_status returns local buffer metrics."""
    res = await human_review_server.call_tool("sync_status", {})
    data = extract_json(res)

    assert data["mode"] == "local_only"
    assert "local_buffer" in data
    assert data["local_buffer"]["skills"] == 0
