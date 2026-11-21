"""Pull JSON objects out of a model's reply, tolerating code fences and prose around them."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def json_objects(text: str) -> Iterator[dict[str, Any]]:
    """Every JSON object in `text`: fenced blocks first, then the raw text."""
    sources = [m.group(1) for m in _FENCE_RE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for source in sources:
        for start in (i for i, ch in enumerate(source) if ch == "{"):
            try:
                value, _ = decoder.raw_decode(source, start)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value
