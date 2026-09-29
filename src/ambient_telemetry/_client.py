from __future__ import annotations

import logging
import re
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

import sentry_sdk

from . import _context
from ._types import Data, Level, TelemetryConfig
from ._umami import UmamiTransport
from ._urls import scrub_breadcrumb, scrub_event

log = logging.getLogger("ambient_telemetry")

_MAX_PENDING = 50
_SENSITIVE = re.compile(
    r"pass(word)?|secret|token|authorization|api[-_]?key|cookie", re.IGNORECASE
)


def scrub(value: Any, depth: int = 0) -> Any:
    """Redact obviously sensitive keys (same rule as the TypeScript library)."""
    if depth > 5:
        return value
    if isinstance(value, dict):
        return {
            k: "[redacted]" if _SENSITIVE.search(str(k)) else scrub(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub(v, depth + 1) for v in value]
    return value


def normalize_error(err: object) -> BaseException:
    if isinstance(err, BaseException):
        return err
    if isinstance(err, str):
        return Exception(err)
    return Exception(f"Non-Error raised: {err!r}")


def _chain(
    ours: Callable[[Any, Any], Any], theirs: Callable[[Any, Any], Any] | None
) -> Callable[[Any, Any], Any]:
    """Run our URL scrubber first, then the app's own Sentry hook (if any)."""

    def hook(item: Any, hint: Any) -> Any:
        item = ours(item, hint)
        return theirs(item, hint) if theirs and item is not None else item

    return hook


class Telemetry:
    """The API contract shared with the TypeScript library:
    init, track, page, capture_error, identify, flush. Nothing here raises."""

    def __init__(self) -> None:
        self._cfg: TelemetryConfig | None = None
        self._umami: UmamiTransport | None = None
        self._pending: deque[Callable[[], None]] = deque(maxlen=_MAX_PENDING)
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def init(self, config: TelemetryConfig) -> None:
        if not config.app or not config.environment:
            log.error("telemetry: `app` and `environment` are required")
            return
        if config.enabled:
            try:
                if config.glitchtip:
                    options = dict(config.sentry_options)
                    if config.sanitize_url:
                        options["before_send"] = _chain(
                            lambda e, h: scrub_event(e, config.sanitize_url),
                            options.get("before_send"),
                        )
                        options["before_breadcrumb"] = _chain(
                            lambda c, h: scrub_breadcrumb(c, config.sanitize_url),
                            options.get("before_breadcrumb"),
                        )
                    sentry_sdk.init(
                        dsn=config.glitchtip.dsn,
                        environment=config.environment,
                        release=config.release,
                        sample_rate=config.glitchtip.sample_rate,
                        traces_sample_rate=config.glitchtip.traces_sample_rate,
                        send_default_pii=False,
                        **options,
                    )
                    sentry_sdk.set_tag("app", config.app)
                if config.umami:
                    self._umami = UmamiTransport(
                        config.umami, sanitize_url=config.sanitize_url
                    )
            except Exception as exc:  # noqa: BLE001
                log.error("telemetry init failed: %s", exc)
        with self._lock:
            self._cfg = config
            queued = list(self._pending)
            self._pending.clear()
        for fn in queued:
            self._call(fn)

    # -- public API --------------------------------------------------------
    def track(
        self, name: str, data: Data | None = None, *, url: str | None = None
    ) -> None:
        def run() -> None:
            cfg, ctx = self._cfg, _context.current()
            assert cfg is not None
            payload: Data | None = scrub(data) if data else None
            ev: tuple[str, Data | None] | None = (name, payload)
            if cfg.before_track:
                ev = cfg.before_track(name, payload)
            if ev is None or self._umami is None:
                return
            merged: Data = {**(ev[1] or {})}
            if ctx.org_id:
                merged.setdefault("org_id", ctx.org_id)
            if ctx.session_id:
                merged.setdefault("session_id", ctx.session_id)
            self._umami.event(
                url=url or "/",
                name=ev[0],
                data=merged or None,
                distinct_id=ctx.user_id,
            )

        self._call(run)

    def page(self, url: str, title: str | None = None) -> None:
        def run() -> None:
            if self._umami:
                self._umami.event(
                    url=url, title=title, distinct_id=_context.current().user_id
                )

        self._call(run)

    def capture_error(
        self,
        err: object,
        *,
        tags: dict[str, str] | None = None,
        extra: Data | None = None,
        level: Level | None = None,
    ) -> None:
        def run() -> None:
            cfg, ctx = self._cfg, _context.current()
            assert cfg is not None
            if not cfg.glitchtip:
                return
            initial: tuple[BaseException, Data] = (
                normalize_error(err),
                {
                    "tags": {"app": cfg.app, **(tags or {})},
                    "extra": scrub(extra) if extra else None,
                    "level": level,
                },
            )
            out: tuple[BaseException, Data] | None = initial
            if cfg.before_send:
                out = cfg.before_send(initial[0], initial[1])
            if out is None:
                return
            exc, meta = out
            with sentry_sdk.new_scope() as scope:
                for k, v in (meta.get("tags") or {}).items():
                    scope.set_tag(k, v)
                if ctx.org_id:
                    scope.set_tag("org_id", ctx.org_id)
                if ctx.session_id:
                    scope.set_tag("session_id", ctx.session_id)
                if ctx.user_id:
                    scope.set_user({"id": ctx.user_id})
                for k, v in (meta.get("extra") or {}).items():
                    scope.set_extra(k, v)
                if meta.get("level"):
                    scope.set_level(meta["level"])
                sentry_sdk.capture_exception(exc)

        self._call(run)

    def identify(self, user_id: str, traits: Data | None = None) -> None:
        def run() -> None:
            _context.bind(user_id=user_id)
            sentry_sdk.set_user({"id": user_id})
            if self._umami:
                self._umami.identify(user_id, scrub(traits) if traits else None)

        self._call(run)

    def flush(self, timeout: float = 2.0) -> bool:
        ok = True
        try:
            sentry_sdk.flush(timeout=timeout)
        except Exception:  # noqa: BLE001
            ok = False
        if self._umami:
            ok = self._umami.flush(timeout) and ok
        return ok

    # -- internals ---------------------------------------------------------
    def _call(self, fn: Callable[[], None]) -> None:
        with self._lock:
            if self._cfg is None:
                self._pending.append(fn)
                return
            cfg = self._cfg
        if not cfg.enabled:
            return
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - telemetry must never raise into the app
            if cfg.debug:
                log.debug("swallowed telemetry error: %s", exc)
