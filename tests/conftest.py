"""Shared pytest fixtures.

Unit tests need nothing external. Integration tests (marked `integration`) need
a built `servoshell`; they auto-skip when no binary is found, so `pytest` is
green on a machine that has only checked out the harness.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from servo_agent.browser import ServoBrowser, find_servoshell

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample.html"


@pytest.fixture(scope="session")
def sample_html() -> str:
    return SAMPLE.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def sample_url() -> str:
    return SAMPLE.resolve().as_uri()  # file:// URL — deterministic, no network


@pytest.fixture(scope="session")
def browser():
    """A session-shared headless engine; skips the whole integration suite if absent."""
    if find_servoshell() is None:
        pytest.skip("servoshell not built (set $SERVOSHELL or build the servo fork)")
    b = ServoBrowser(headless=True)
    try:
        b.ensure_started()
        yield b
    finally:
        b.shutdown()
