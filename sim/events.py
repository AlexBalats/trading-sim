"""Market events: rumours, YouTuber videos, new sets, reprints.

Empty in iteration 1. The engine already calls apply_events every day, so
events can be added here later without touching the day loop.
"""

from __future__ import annotations

from .state import World


def apply_events(day: int, world: World) -> None:
    pass
