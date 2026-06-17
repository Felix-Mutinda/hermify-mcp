"""
eval.py — Evaluation pipeline for hermify-mcp YOLO governance.
Defines the interface for LLM-as-a-Judge skill evaluation.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EvalJudge(Protocol):
    """Interface for evaluating a skill draft."""

    def evaluate(self, skill_md: str) -> float:
        """
        Evaluate the skill and return a score between 0.0 and 1.0.
        """
        ...


class MockEvalJudge:
    """
    A deterministic mock judge for testing and local-only demos.
    Always returns a predefined score.
    """

    def __init__(self, score: float = 0.95, name: str = "mock-judge"):
        self.score = score
        self.name = name

    def evaluate(self, skill_md: str) -> float:
        logger.info(
            f"[{self.name}] Evaluating skill... returning fixed score {self.score}"
        )
        return self.score


class PassThroughJudge:
    """
    A fallback judge that always returns 0.0.
    Used when YOLO mode is accidentally enabled without a real judge configured.
    """

    def evaluate(self, skill_md: str) -> float:
        logger.warning(
            "PassThroughJudge used. No real LLM Judge configured. Rejecting skill."
        )
        return 0.0
