"""Shared fixtures for the Financial Research System test suite."""

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
