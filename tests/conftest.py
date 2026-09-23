"""Shared pytest fixtures.

pytest-asyncio opens a fresh event loop per test function by default,
but `src.db.engine` is a module-level singleton whose connection pool
gets bound to whichever loop first used it. Without disposing the pool
after each test, the next test's loop tries to reuse connections bound
to an already-closed loop and crashes with "Event loop is closed".
Disposing after every test forces the next checkout to open a fresh
connection on the current loop.
"""
import pytest

from src.db import engine


@pytest.fixture(autouse=True)
async def _dispose_engine_pool_after_test():
    yield
    await engine.dispose()
