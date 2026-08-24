"""Clipboard parsers for Path of Exile crafting tooltips."""

import re

from .models import CurrencyStackState, ItemSocketState


class ClipboardParseError(ValueError):
    """Clipboard text was not the expected PoE item or currency tooltip."""


_SOCKET_LINE = re.compile(r"^Sockets:\s*(.+?)\s*$", re.MULTILINE)
_SOCKET_TOKEN = re.compile(r"[RGBW]", re.IGNORECASE)
_STACK_LINE = re.compile(r"^Stack Size:\s*([0-9][0-9,]*)\s*/\s*([0-9][0-9,]*)\s*$", re.MULTILINE)


def parse_poe1_socket_state(item_text: str) -> ItemSocketState:
    """Parse socket count and largest linked group from copied PoE 1 item text."""
    if not isinstance(item_text, str):
        raise ClipboardParseError("Clipboard did not contain text")
    match = _SOCKET_LINE.search(item_text.replace("\r\n", "\n"))
    if not match:
        raise ClipboardParseError("Copied item has no Sockets line")
    raw = match.group(1).strip()
    groups = [group for group in raw.split() if group]
    counts = [len(_SOCKET_TOKEN.findall(group)) for group in groups]
    counts = [count for count in counts if count]
    if not counts:
        raise ClipboardParseError("Sockets line contains no supported sockets")
    return ItemSocketState(
        socket_count=sum(counts),
        max_link_group=max(counts),
        raw_sockets_line=raw,
    )


def parse_poe1_currency_stack(currency_text: str, expected_name: str) -> CurrencyStackState:
    """Validate an exact currency name and parse its current currency-tab stack count."""
    if not isinstance(currency_text, str):
        raise ClipboardParseError("Clipboard did not contain text")
    normalized = currency_text.replace("\r\n", "\n")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if "Item Class: Stackable Currency" not in lines:
        raise ClipboardParseError("Copied entry is not Stackable Currency")
    if expected_name not in lines:
        observed = next((line for line in lines if line.endswith("Orb")), "unknown currency")
        raise ClipboardParseError(f"Expected {expected_name}, found {observed}")
    stack = _STACK_LINE.search(normalized)
    if not stack:
        raise ClipboardParseError(f"Could not read {expected_name} stack size")
    count = int(stack.group(1).replace(",", ""))
    limit = int(stack.group(2).replace(",", ""))
    if count < 1:
        raise ClipboardParseError(f"{expected_name} stack is empty")
    return CurrencyStackState(expected_name, count, limit)


def goal_is_met(state: ItemSocketState, mode, target: int) -> bool:
    value = state.socket_count if str(getattr(mode, "value", mode)) == "sockets" else state.max_link_group
    return value >= int(target)
