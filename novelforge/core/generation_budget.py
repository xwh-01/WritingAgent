"""Request-scoped hard budgets for generated prose workflows."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Iterator

from novelforge.llm.base import LLMResponse


class GenerationBudgetExceeded(RuntimeError):
    """Raised before a generation call that would exceed its global allowance."""


@dataclass(frozen=True)
class BudgetReservation:
    estimated_tokens: int


@dataclass
class GenerationBudget:
    """Track and enforce one chapter-generation call/token envelope.

    Providers do not always return usage metadata.  In that case conservative
    text estimates remain part of the accounting and are explicitly surfaced in
    the report, rather than silently allowing an unbounded path.
    """

    max_calls: int | None = None
    max_tokens: int | None = None
    per_call_max_tokens: int = 2400
    calls_used: int = 0
    tokens_used: int = 0
    estimated_tokens_used: bool = False
    exhausted_reason: str = ""
    operations: list[str] = field(default_factory=list)

    @property
    def remaining_calls(self) -> int | None:
        return None if self.max_calls is None else max(0, self.max_calls - self.calls_used)

    @property
    def remaining_tokens(self) -> int | None:
        return None if self.max_tokens is None else max(0, self.max_tokens - self.tokens_used)

    def prepare(
        self,
        messages: list[dict[str, str]],
        kwargs: dict[str, Any],
    ) -> tuple[dict[str, Any], BudgetReservation]:
        if self.max_calls is not None and self.calls_used >= self.max_calls:
            self.exhausted_reason = "max_calls"
            raise GenerationBudgetExceeded("Generation call budget exhausted.")

        prompt_tokens = self._estimate_messages(messages)
        requested = kwargs.get("max_tokens")
        try:
            requested_tokens = int(requested) if requested is not None else self.per_call_max_tokens
        except (TypeError, ValueError):
            requested_tokens = self.per_call_max_tokens
        requested_tokens = max(1, min(requested_tokens, self.per_call_max_tokens))
        if self.max_tokens is not None:
            remaining = self.max_tokens - self.tokens_used
            allowed_completion = remaining - prompt_tokens
            if allowed_completion < 1:
                self.exhausted_reason = "max_tokens"
                raise GenerationBudgetExceeded("Generation token budget exhausted.")
            requested_tokens = min(requested_tokens, allowed_completion)
        estimated = prompt_tokens + requested_tokens
        if self.max_tokens is not None and self.tokens_used + estimated > self.max_tokens:
            self.exhausted_reason = "max_tokens"
            raise GenerationBudgetExceeded("Generation token budget exhausted.")
        prepared = dict(kwargs)
        prepared["max_tokens"] = requested_tokens
        self.calls_used += 1
        self.tokens_used += estimated
        return prepared, BudgetReservation(estimated_tokens=estimated)

    def record(self, reservation: BudgetReservation, response: LLMResponse) -> None:
        actual = response.total_tokens
        if actual is None:
            actual = self._estimate_text(response.content)
            self.estimated_tokens_used = True
        self.tokens_used = max(0, self.tokens_used - reservation.estimated_tokens + int(actual))
        if response.operation:
            self.operations.append(response.operation)
        if self.max_tokens is not None and self.tokens_used >= self.max_tokens:
            self.exhausted_reason = self.exhausted_reason or "max_tokens"

    @staticmethod
    def _estimate_messages(messages: list[dict[str, str]]) -> int:
        return max(1, sum(GenerationBudget._estimate_text(item.get("content", "")) for item in messages))

    @staticmethod
    def _estimate_text(text: str) -> int:
        # A deliberately conservative mixed Chinese/English estimate.  This is
        # only used when a provider does not return authoritative usage.
        return max(1, (len(text or "") + 2) // 3)


_ACTIVE_BUDGET: ContextVar[GenerationBudget | None] = ContextVar("active_generation_budget", default=None)


def current_generation_budget() -> GenerationBudget | None:
    return _ACTIVE_BUDGET.get()


def budgeted_chat_completion(
    llm: Any,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> str:
    """Make one provider call while honoring the active generation budget."""
    budget = current_generation_budget()
    if budget is None:
        return llm.chat_completion(messages, **kwargs)
    prepared, reservation = budget.prepare(messages, kwargs)
    response = llm.chat_completion_result(messages, **prepared)
    budget.record(reservation, response)
    return response.content


@contextmanager
def generation_budget_scope(budget: GenerationBudget) -> Iterator[GenerationBudget]:
    token: Token[GenerationBudget | None] = _ACTIVE_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE_BUDGET.reset(token)


__all__ = [
    "GenerationBudget",
    "GenerationBudgetExceeded",
    "BudgetReservation",
    "budgeted_chat_completion",
    "current_generation_budget",
    "generation_budget_scope",
]
