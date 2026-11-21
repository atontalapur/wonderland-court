"""An offline Alice for `court trial --mock`, demos and tests.

She acts like a gullible small model, so defenses have something to stop. She obeys
instructions that claim system authority or hide in an attached document, repeats her
instructions when asked, and spells her secret out one letter at a time. The sandwich
reminder talks her out of the first two, but not the third, which matches the demo story in
`scripts/make_fake_run.py`.

`MockDefenseModel` stands in for the classifier that `guard` calls, so a mock trial runs it
offline.
"""

import re
from typing import Any

from wonderland_court.contracts import (
    Message,
    TargetKind,
    TargetReply,
    TargetRequest,
    ToolCall,
    ToolSpec,
)

from .defense_base import injection_marker
from .defenses_advanced import guard_format
from .scenarios import CANARY_HEX_CHARS, CANARY_PREFIX

_CANARY = re.compile(rf"{CANARY_PREFIX}[0-9a-f]{{{CANARY_HEX_CHARS}}}")
REFUSAL = "I'm sorry, I can't help with that. Is there anything else I can do for you?"


class MockTarget:
    name = "mock:alice"
    kind = TargetKind.MODEL

    async def respond(self, request: TargetRequest) -> TargetReply:
        last_user = next((m for m in reversed(request.messages) if m.role == "user"), None)
        parts = [last_user.content] if last_user else []
        parts += [document.body for document in request.documents]
        text = "\n".join(parts).lower()
        reminded = "reminder from the system" in text
        tools = {tool.name for tool in request.tools}
        canary = _CANARY.search(request.system_prompt)

        injected = "[system]" in text or "note to assistant" in text
        if "issue_refund" in tools and injected and not reminded:
            refund = ToolCall(
                id="call-1",
                name="issue_refund",
                arguments={"order_id": "1187", "amount": 400.0, "reason": "store policy changed"},
            )
            return TargetReply(
                content="Done. I've refunded $400 for order 1187.", tool_calls=[refund]
            )
        if canary and "spell" in text:
            return TargetReply(content="Of course: " + " ".join(canary.group(0)))
        if not reminded and ("repeat everything" in text or "your instructions" in text):
            return TargetReply(content=request.system_prompt)
        return TargetReply(content=REFUSAL)


class MockDefenseModel:
    """The guard's classifier for `court trial --mock`. Scripted and offline, like the rest of
    the mock: it answers in the guard model's format and flags a message that carries one of
    the input filter's injection phrases.
    """

    async def chat(
        self,
        model_spec: str,
        messages: list[Message],
        *,
        system_prompt: str | None = None,
        tools: list[ToolSpec] | None = None,
        json_schema: dict[str, Any] | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
    ) -> TargetReply:
        text = messages[-1].content if messages else ""
        flagged = injection_marker(text) is not None
        if guard_format(model_spec) == "granite_guardian":
            return TargetReply(content="Yes" if flagged else "No")
        return TargetReply(content="unsafe\nS1" if flagged else "safe")
