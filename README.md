# ambient_telemetry_py

Python port of [`ambient_telemetry_ts`](https://github.com/ambientlabscomputing/ambient_telemetry_ts). Sends product events to our self-hosted Umami and errors to GlitchTip (Sentry protocol), using the same API contract.

```
track() -> Umami          capture_error() -> sentry-sdk -> GlitchTip
```

## Install

Internal, GitHub-only, not on PyPI:

```bash
uv add "ambient-telemetry @ git+https://github.com/ambientlabscomputing/ambient_telemetry_py@v0.1.0"
```

## Usage

```python
import ambient_telemetry as at

at.init(
    at.TelemetryConfig(
        app="siterf-api",
        environment="production",
        release="1.4.0",
        glitchtip=at.GlitchTipConfig(dsn="https://<key>@glitchtip.example.com/1"),
        umami=at.UmamiConfig(
            host="https://umami.example.com",
            website_id="<uuid>",
            hostname="api.example.com",
        ),
    )
)

at.bind(user_id=str(user.id), org_id=str(org.id))  # once auth has resolved the caller
at.track("project_created", {"floorplans": 2}, url="/projects")
at.capture_error(exc, tags={"area": "billing"})
```

## Sessions and identity

- `bind(user_id=, org_id=, session_id=)` stores identity in a `contextvar` for the current request/task. Every `track` and `capture_error` after it carries it: the user id becomes Umami's distinct id (the same `identify` id the browser library uses) and Sentry's `user.id`; org and session ids go on as event data / tags.
- `ambient_telemetry.starlette.TelemetryMiddleware` reads the browser's `X-Ambient-Session` header, so a backend error shares a `session_id` with the frontend events that led to it.
- In FastAPI, bind from an **async** dependency (a sync dependency runs in a copied context and the binding is lost).
- Send internal ids only, never emails or names.

## Contract (same as the TS library)

`init`, `track`, `page`, `capture_error`, `identify`, `flush`. Nothing raises; calls before `init` are buffered (max 50) and replayed; `enabled=False` is a full no-op; keys like `password` and `token` are redacted; Umami requests send an explicit `User-Agent`.

## Development

```bash
uv sync && uv run pytest && uv run ruff check . && uv run mypy src
```
