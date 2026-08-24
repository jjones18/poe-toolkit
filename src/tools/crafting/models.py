"""Data models for generic crafting workflows."""

from dataclasses import dataclass
from enum import Enum


class CraftingMode(str, Enum):
    SOCKETS = "sockets"
    LINKS = "links"


@dataclass(frozen=True)
class ScreenPoint:
    x: int
    y: int


@dataclass(frozen=True)
class ItemSocketState:
    socket_count: int
    max_link_group: int
    raw_sockets_line: str


@dataclass(frozen=True)
class CurrencyStackState:
    name: str
    stack_count: int
    stack_limit: int


@dataclass(frozen=True)
class CraftingGoal:
    mode: CraftingMode
    target: int
    max_attempts: int = 0
    verify_only: bool = False


@dataclass(frozen=True)
class CraftingRunResult:
    success: bool
    attempts: int
    reason: str
    final_state: ItemSocketState | None = None
