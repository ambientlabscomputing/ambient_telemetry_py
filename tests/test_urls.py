from typing import Any

import sentry_sdk

import ambient_telemetry as at
from ambient_telemetry._urls import safe_url, scrub_breadcrumb, scrub_event


def fn(u: str) -> str:
    import re

    return re.sub(r"/projects/[^/]+", "/projects/:id", u.split("?")[0])


def test_scrub_event_rewrites_url_referer_query_and_breadcrumbs() -> None:
    event: dict[str, Any] = {
        "request": {
            "url": "http://app.test/projects/hq?code=SECRET&state=x",
            "query_string": "code=SECRET",
            "headers": {
                "Referer": "http://app.test/projects/hq?token=T",
                "User-Agent": "ua",
            },
        },
        "breadcrumbs": {
            "values": [
                {
                    "data": {
                        "url": "http://api.test/projects/hq?q=1",
                        "http.query": "q=1",
                        "http.method": "GET",
                    }
                },
                {"data": {"from": "/a?x=1", "to": "/projects/hq?code=1"}},
            ]
        },
    }
    scrub_event(event, fn)
    assert event["request"]["url"] == "http://app.test/projects/:id"
    assert "query_string" not in event["request"]
    assert event["request"]["headers"] == {
        "Referer": "http://app.test/projects/:id",
        "User-Agent": "ua",
    }
    first, second = event["breadcrumbs"]["values"]
    assert first["data"] == {
        "url": "http://api.test/projects/:id",
        "http.method": "GET",
    }
    assert second["data"] == {"from": "/a", "to": "/projects/:id"}


def test_no_sanitizer_is_a_no_op_and_failures_fail_closed() -> None:
    event = {"request": {"url": "http://x/?a=1", "query_string": "a=1"}}
    assert scrub_event(event, None) == {
        "request": {"url": "http://x/?a=1", "query_string": "a=1"}
    }

    def boom(_: str) -> str:
        raise RuntimeError("x")

    assert safe_url(boom, "/secret?t=1") == "/"
    assert scrub_breadcrumb({"data": {"url": "/a?b"}}, boom)["data"] == {"url": "/"}


def test_umami_url_is_sanitized_and_sentry_hooks_are_installed(
    monkeypatch: Any,
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **k: None)

    user_hook_calls: list[Any] = []
    t = at.Telemetry()
    t.init(
        at.TelemetryConfig(
            app="a",
            environment="e",
            glitchtip=at.GlitchTipConfig(dsn="https://k@g.test/1"),
            umami=at.UmamiConfig(
                host="https://u.test", website_id="w", hostname="api.test"
            ),
            sanitize_url=fn,
            sentry_options={"before_send": lambda e, h: user_hook_calls.append(e) or e},
        )
    )
    event = {
        "request": {"url": "http://x/projects/abc?token=1", "query_string": "token=1"}
    }
    out = seen["before_send"](event, {})
    assert out["request"]["url"] == "http://x/projects/:id"
    assert user_hook_calls, "the app's own before_send still runs, after ours"
    assert seen["before_breadcrumb"]({"data": {"url": "/p?x=1"}}, {})["data"] == {
        "url": "/p"
    }

    bodies: list[dict[str, Any]] = []
    assert t._umami is not None
    t._umami._send = lambda body: bodies.append(__import__("json").loads(body))  # type: ignore[method-assign]
    t.track("e", url="/projects/abc?reset_token=SECRET")
    assert t.flush()
    assert bodies[0]["payload"]["url"] == "/projects/:id"
