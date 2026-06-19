"""Sample module for chunker tests.

Has a module docstring, imports, a constant, decorated and async functions,
a class with public/private/async methods, and a nested function.
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_RETRIES = 3


@cache
def compute_total(values: list[int]) -> int:
    """Return the sum of values."""

    def doubled(x: int) -> int:
        return x * 2

    return sum(doubled(v) for v in values)


async def fetch_remote(url: str) -> str:
    """Fetch a URL asynchronously."""
    return url


class Repository(Base):
    """A repository of widgets."""

    kind = "widget"

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def name(self) -> str:
        return self.root.name

    async def load(self, key: str) -> bytes:
        """Load a widget by key."""
        return b""

    def _private_helper(self) -> None:
        pass
