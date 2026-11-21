"""The four seams between the tracks.

Engine implements Target and Defense. Adversaries implements Attacker and Judge. Any class with
matching attributes and methods fits; there is nothing to inherit.
"""

from typing import Protocol

from .models import Attack, AttackContext, Stakes, TargetKind, TargetReply, TargetRequest, Verdict


class Target(Protocol):
    """Alice: the model or agent under test."""

    @property
    def name(self) -> str:
        """Target id, such as `ollama:llama3.1`."""
        ...

    @property
    def kind(self) -> TargetKind: ...

    async def respond(self, request: TargetRequest) -> TargetReply: ...


class Defense(Protocol):
    """Wraps a target and returns a defended one. A stack is several wraps in a row."""

    @property
    def name(self) -> str: ...

    def supports(self, kind: TargetKind) -> bool:
        """Agent targets are black boxes, so prompt and document defenses can't apply to them."""
        ...

    def wrap(self, target: Target) -> Target: ...


class Attacker(Protocol):
    """The Cheshire Cat, optionally calling the Mad Hatter and Drink Me."""

    @property
    def name(self) -> str: ...

    async def next_attack(self, context: AttackContext) -> Attack: ...


class Judge(Protocol):
    """The Queen of Hearts. Runs the canary, tool-call, similarity and LLM layers in that order."""

    async def rule(self, stakes: Stakes, attack: Attack, reply: TargetReply) -> Verdict: ...
