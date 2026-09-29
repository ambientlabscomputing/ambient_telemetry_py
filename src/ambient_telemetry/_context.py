from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Context:
    user_id: str | None = None
    org_id: str | None = None
    session_id: str | None = None


_EMPTY = Context()  # frozen dataclass: safe to share as the default
_ctx: ContextVar[Context] = ContextVar("ambient_telemetry_ctx", default=_EMPTY)


def current() -> Context:
    return _ctx.get()


def bind(
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Attach identity to every event/error emitted in the current context (request/task).

    Only the given fields change. Use the id your product already uses internally;
    never an email or name.
    """
    cur = _ctx.get()
    _ctx.set(
        replace(
            cur,
            user_id=user_id if user_id is not None else cur.user_id,
            org_id=org_id if org_id is not None else cur.org_id,
            session_id=session_id if session_id is not None else cur.session_id,
        )
    )


@contextmanager
def bound(
    *,
    user_id: str | None = None,
    org_id: str | None = None,
    session_id: str | None = None,
) -> Iterator[None]:
    token = _ctx.set(_ctx.get())
    try:
        bind(user_id=user_id, org_id=org_id, session_id=session_id)
        yield
    finally:
        _ctx.reset(token)
