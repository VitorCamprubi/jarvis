"""Bilingual rule-based router; anything it cannot resolve goes to the LLM (Phase 3)."""

from jarvis.router.router import Route, Router

__all__ = ["Route", "Router"]
