import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

import ambient_telemetry as at
from ambient_telemetry._ip import public_ip
from ambient_telemetry.starlette import TelemetryMiddleware


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8.8.8.8", "8.8.8.8"),
        (" 8.8.8.8 ", "8.8.8.8"),
        ("8.8.8.8:51234", "8.8.8.8"),
        ("2001:4860:4860::8888", "2001:4860:4860::8888"),
        ("[2001:4860:4860::8888]:443", "2001:4860:4860::8888"),
        (
            "2400:cb00:0:1:1:1:1:1",
            "2400:cb00:0:1:1:1:1:1",
        ),  # one zero group: not compressed
        (
            "2400:cb00:0:0:1:0:0:1",
            "2400:cb00::1:0:0:1",
        ),  # equal runs: the first is compressed
        ("2400:cb00:0:1:0:0:0:1", "2400:cb00:0:1::1"),  # the longest run wins
        ("::ffff:8.8.8.8", "8.8.8.8"),  # IPv4-mapped IPv6 is the v4 address
        # Not a public address: never record a proxy's or a LAN's address as the user's.
        ("10.0.0.5", None),
        ("192.168.1.9", None),
        ("172.16.4.2", None),
        ("127.0.0.1", None),
        ("::1", None),
        ("fe80::1", None),
        ("169.254.1.1", None),
        ("100.64.0.1", None),  # carrier-grade NAT
        ("::ffff:10.0.0.5", None),
        ("ff02::1", None),  # multicast
        ("224.0.0.1", None),
        ("64:ff9b::808:808", None),  # NAT64
        ("1:2:3:4:5:6:7:8", None),  # not global unicast
        ("2002:808:808::1", None),  # 6to4
        ("2001::1", None),  # Teredo / IETF protocol assignments
        ("3fff::1", None),  # documentation
        ("01.2.3.4", None),  # leading zeros are ambiguous (octal)
        # Junk.
        ("", None),
        ("unknown", None),
        ("8.8.8.8, 1.1.1.1", None),
        ("[2001:4860::1", None),
        ("x" * 100, None),
        (None, None),
        (b"8.8.8.8", None),
    ],
)
def test_public_ip(raw: object, expected: str | None) -> None:
    assert public_ip(raw) == expected


def test_bind_ignores_non_public_ip_and_keeps_the_previous_one() -> None:
    with at.bound(ip="8.8.8.8"):
        assert at.current_context().ip == "8.8.8.8"
        at.bind(ip="10.0.0.1")
        assert at.current_context().ip == "8.8.8.8"
        at.bind(user_id="u-1")  # unrelated fields don't touch it
        assert at.current_context().ip == "8.8.8.8"
    assert at.current_context().ip is None


def make(**cfg: Any) -> tuple[at.Telemetry, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    t = at.Telemetry()
    t.init(
        at.TelemetryConfig(
            app="demo",
            environment="test",
            umami=at.UmamiConfig(
                host="https://u.test", website_id="w1", hostname="api.test"
            ),
            **cfg,
        )
    )
    assert t._umami is not None
    t._umami._send = lambda body: sent.append(json.loads(body))  # type: ignore[method-assign]
    return t, sent


def test_umami_gets_the_users_ip_when_capture_ip_is_on() -> None:
    t, sent = make(capture_ip=True)
    with at.bound(user_id="u-1", ip="8.8.8.8"):
        t.track("clicked", {"n": 1}, url="/x")
        t.page("/y", "Y")
        t.identify("u-1", {"plan": "pro"})
    assert t.flush()
    track, page, identify = (b["payload"] for b in sent)
    assert track["ip"] == "8.8.8.8"
    assert track["data"] == {"n": 1, "client_ip": "8.8.8.8"}
    assert page["ip"] == "8.8.8.8"
    assert identify["ip"] == "8.8.8.8"


def test_nothing_is_recorded_unless_capture_ip_is_on() -> None:
    t, sent = make()  # default: off
    with at.bound(user_id="u-1", ip="8.8.8.8"):
        t.track("clicked", {"n": 1}, url="/x")
        t.page("/y")
        t.identify("u-1")
    assert t.flush()
    for b in sent:
        assert "ip" not in b["payload"]
        assert "client_ip" not in json.dumps(b)


def test_no_ip_bound_means_no_ip_field() -> None:
    t, sent = make(capture_ip=True)
    t.track("clicked", url="/x")
    assert t.flush()
    assert "ip" not in sent[0]["payload"]
    assert "data" not in sent[0]["payload"]


def test_before_track_cannot_be_bypassed_by_the_ip_property() -> None:
    # client_ip is added after before_track, like org_id/session_id; dropping still works.
    t, sent = make(capture_ip=True, before_track=lambda n, d: None)
    with at.bound(ip="8.8.8.8"):
        t.track("clicked")
    assert t.flush()
    assert sent == []


class Capture(Transport):
    """In-memory stand-in for GlitchTip: records the error events sentry-sdk would send."""

    def __init__(self, sink: list[dict[str, Any]]) -> None:
        super().__init__()
        self.sink = sink

    def capture_envelope(self, envelope: Any) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.sink.append(item.payload.json)


@pytest.fixture
def glitchtip_events() -> Iterator[list[dict[str, Any]]]:
    yield []
    client = sentry_sdk.get_client()
    client.close()


def sentry_telemetry(events: list[dict[str, Any]], **cfg: Any) -> at.Telemetry:
    t = at.Telemetry()
    t.init(
        at.TelemetryConfig(
            app="demo",
            environment="test",
            glitchtip=at.GlitchTipConfig(dsn="https://k@g.test/1"),
            sentry_options={
                "transport": Capture(events),
                "default_integrations": False,
            },
            **cfg,
        )
    )
    return t


def test_capture_error_tags_the_users_ip(
    glitchtip_events: list[dict[str, Any]],
) -> None:
    t = sentry_telemetry(glitchtip_events, capture_ip=True)
    with at.bound(user_id="u-1", ip="8.8.8.8"):
        t.capture_error(RuntimeError("boom"))
    assert glitchtip_events[0]["tags"]["client_ip"] == "8.8.8.8"
    assert glitchtip_events[0]["tags"]["app"] == "demo"


def test_errors_sentry_captures_on_its_own_are_tagged_too(
    glitchtip_events: list[dict[str, Any]],
) -> None:
    # Unhandled 5xx never go through capture_error(): the before_send hook covers them.
    sentry_telemetry(glitchtip_events, capture_ip=True)
    with at.bound(ip="8.8.8.8"):
        sentry_sdk.capture_exception(RuntimeError("unhandled"))
    assert glitchtip_events[0]["tags"]["client_ip"] == "8.8.8.8"


def test_an_explicit_client_ip_tag_wins_over_the_bound_one(
    glitchtip_events: list[dict[str, Any]],
) -> None:
    t = sentry_telemetry(glitchtip_events, capture_ip=True)
    with at.bound(ip="8.8.8.8"):
        t.capture_error(RuntimeError("boom"), tags={"client_ip": "custom"})
    assert glitchtip_events[0]["tags"]["client_ip"] == "custom"


def test_sentry_gets_no_ip_when_off_or_unbound(
    glitchtip_events: list[dict[str, Any]],
) -> None:
    t = sentry_telemetry(glitchtip_events)  # off
    with at.bound(ip="8.8.8.8"):
        t.capture_error(RuntimeError("a"))
        sentry_sdk.capture_exception(RuntimeError("b"))
    assert all("client_ip" not in (e.get("tags") or {}) for e in glitchtip_events)

    glitchtip_events.clear()
    sentry_sdk.get_client().close()
    t = sentry_telemetry(glitchtip_events, capture_ip=True)  # on, nothing bound
    t.capture_error(RuntimeError("c"))
    assert "client_ip" not in glitchtip_events[0]["tags"]


def test_users_own_before_send_still_runs_after_ours(
    glitchtip_events: list[dict[str, Any]],
) -> None:
    seen: list[Any] = []
    t = at.Telemetry()
    t.init(
        at.TelemetryConfig(
            app="demo",
            environment="test",
            glitchtip=at.GlitchTipConfig(dsn="https://k@g.test/1"),
            capture_ip=True,
            sentry_options={
                "transport": Capture(glitchtip_events),
                "default_integrations": False,
                "before_send": lambda e, h: (
                    seen.append(e["tags"].get("client_ip")) or e
                ),
            },
        )
    )
    with at.bound(ip="8.8.8.8"):
        sentry_sdk.capture_exception(RuntimeError("x"))
    assert seen == ["8.8.8.8"]


def bound_ip(mw_kwargs: dict[str, Any], scope: dict[str, Any]) -> str | None:
    seen: list[str | None] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(at.current_context().ip)

    asyncio.run(
        TelemetryMiddleware(app, **mw_kwargs)({"type": "http", **scope}, None, None)
    )
    return seen[0]


def test_middleware_uses_the_peer_address_by_default() -> None:
    assert bound_ip({}, {"client": ("8.8.8.8", 5000), "headers": []}) == "8.8.8.8"


def test_middleware_ignores_client_controlled_forwarding_headers_by_default() -> None:
    scope = {
        "client": ("8.8.8.8", 5000),
        "headers": [(b"x-forwarded-for", b"1.1.1.1"), (b"x-real-ip", b"1.1.1.1")],
    }
    assert bound_ip({}, scope) == "8.8.8.8"  # not spoofable


def test_middleware_ignores_a_private_peer_such_as_a_load_balancer() -> None:
    assert bound_ip({}, {"client": ("10.0.0.7", 5000), "headers": []}) is None


def test_middleware_reads_the_configured_trusted_header() -> None:
    scope = {
        "client": ("10.0.0.7", 5000),  # the proxy
        "headers": [(b"cf-connecting-ip", b"1.1.1.1")],
    }
    assert bound_ip({"ip_header": "CF-Connecting-IP"}, scope) == "1.1.1.1"


def test_middleware_reads_only_the_configured_header() -> None:
    scope = {
        "client": ("10.0.0.7", 5000),
        "headers": [
            (b"x-forwarded-for", b"9.9.9.9"),  # valid, but not the one we trust
            (b"x-real-ip", b"1.1.1.1"),
        ],
    }
    assert bound_ip({"ip_header": "x-real-ip"}, scope) == "1.1.1.1"


def test_middleware_takes_the_first_entry_of_a_list_header() -> None:
    scope = {
        "client": ("10.0.0.7", 5000),
        "headers": [(b"x-forwarded-for", b"1.1.1.1, 10.0.0.3")],
    }
    assert bound_ip({"ip_header": "x-forwarded-for"}, scope) == "1.1.1.1"


def test_middleware_falls_back_to_the_peer_when_the_header_is_missing_or_junk() -> None:
    peer = ("8.8.8.8", 5000)
    assert (
        bound_ip({"ip_header": "x-real-ip"}, {"client": peer, "headers": []})
        == "8.8.8.8"
    )
    junk = {"client": peer, "headers": [(b"x-real-ip", b"not-an-ip")]}
    assert bound_ip({"ip_header": "x-real-ip"}, junk) == "8.8.8.8"


def test_middleware_handles_a_missing_client_and_does_not_leak_between_requests() -> (
    None
):
    seen: list[str | None] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(at.current_context().ip)

    async def run() -> None:
        mw = TelemetryMiddleware(app)
        await mw({"type": "http", "client": ("8.8.8.8", 1), "headers": []}, None, None)
        await mw({"type": "http", "headers": []}, None, None)  # e.g. a unix socket

    asyncio.run(run())
    assert seen == ["8.8.8.8", None]
