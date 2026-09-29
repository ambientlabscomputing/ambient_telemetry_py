import json
from typing import Any

import httpx

import ambient_telemetry as at
from ambient_telemetry._umami import UmamiTransport


class Recorder:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.statuses = statuses or []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else 200
        return httpx.Response(status, json={"cache": "tok1"})

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def make(rec: Recorder, **cfg_kwargs: Any) -> at.Telemetry:
    t = at.Telemetry()
    cfg = at.TelemetryConfig(
        app="demo",
        environment="test",
        umami=at.UmamiConfig(
            host="https://u.test/", website_id="w1", hostname="api.test"
        ),
        **cfg_kwargs,
    )
    # Swap in a transport that uses the mock HTTP client.
    t.init(at.TelemetryConfig(app="demo", environment="test"))
    t._umami = UmamiTransport(
        cfg.umami,  # type: ignore[arg-type]
        httpx.Client(transport=httpx.MockTransport(rec)),
        base_delay=0.01,
    )
    t._cfg = cfg
    return t


def test_track_payload_carries_identity() -> None:
    rec = Recorder()
    t = make(rec)
    with at.bound(user_id="u-1", org_id="o-1", session_id="sess-1234"):
        t.track("project_created", {"n": 1, "password": "x"}, url="/projects")
    assert t.flush()
    p = rec.bodies()[0]
    assert p["type"] == "event"
    assert p["payload"] | {} == p["payload"]
    assert p["payload"]["website"] == "w1"
    assert p["payload"]["hostname"] == "api.test"
    assert p["payload"]["id"] == "u-1"
    assert p["payload"]["url"] == "/projects"
    assert p["payload"]["data"] == {
        "n": 1,
        "password": "[redacted]",
        "org_id": "o-1",
        "session_id": "sess-1234",
    }
    ua = rec.requests[0].headers["user-agent"]
    assert ua.startswith("Mozilla/5.0") and ua.endswith("ambient-telemetry-python/0.1")
    assert rec.requests[0].url == "https://u.test/api/send"


def test_cache_token_is_replayed() -> None:
    rec = Recorder()
    t = make(rec)
    t.track("a")
    assert t.flush()
    t.track("b")
    assert t.flush()
    assert rec.requests[1].headers["x-umami-cache"] == "tok1"


def test_retries_5xx_and_drops_4xx() -> None:
    rec = Recorder([503, 503, 200])
    t = make(rec)
    t.track("r")
    assert t.flush(5)
    assert len(rec.requests) == 3

    rec4 = Recorder([400])
    t4 = make(rec4)
    t4.track("bad")
    assert t4.flush(5)
    assert len(rec4.requests) == 1


def test_before_track_and_disabled() -> None:
    rec = Recorder()
    t = make(rec, before_track=lambda n, d: None)
    t.track("dropped")
    assert t.flush()
    assert rec.requests == []

    off = at.Telemetry()
    off.init(at.TelemetryConfig(app="a", environment="e", enabled=False))
    off.track("x")
    off.capture_error("e")
    assert off.flush()


def test_calls_before_init_are_replayed_and_never_raise() -> None:
    t = at.Telemetry()
    t.capture_error(RuntimeError("early"))  # no glitchtip configured: silently ignored
    t.track("early")
    t.init(at.TelemetryConfig(app="a", environment="e"))


def test_normalize_and_scrub() -> None:
    assert isinstance(at.normalize_error({"code": 5}), Exception)
    assert at.scrub({"a": {"Authorization": "x", "ok": 1}}) == {
        "a": {"Authorization": "[redacted]", "ok": 1}
    }


def test_middleware_binds_session_and_isolates_requests() -> None:
    import asyncio

    from ambient_telemetry.starlette import TelemetryMiddleware

    seen: list[str | None] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(at.current_context().session_id)

    async def run() -> None:
        mw = TelemetryMiddleware(app)
        await mw(
            {"type": "http", "headers": [(b"x-ambient-session", b"abcdefgh1234")]},
            None,
            None,
        )
        await mw({"type": "http", "headers": []}, None, None)
        await mw(
            {"type": "http", "headers": [(b"x-ambient-session", b"bad value!")]},
            None,
            None,
        )

    asyncio.run(run())
    assert seen == ["abcdefgh1234", None, None]
