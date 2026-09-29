# ambient_telemetry_py

Python port of [`ambient_telemetry_ts`](https://github.com/ambientlabscomputing/ambient_telemetry_ts). Sends product events to our self-hosted Umami and errors to GlitchTip (Sentry protocol), using the same API contract.

```
track() -> Umami          capture_error() -> sentry-sdk -> GlitchTip
```

## Install

Internal, GitHub-only, not on PyPI:

```bash
uv add "ambient-telemetry @ git+https://github.com/ambientlabscomputing/ambient_telemetry_py@v0.2.0"
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

## Config reference

| Field | Meaning |
|-------|---------|
| `app` (required) | e.g. `myproduct-api`. Becomes the GlitchTip `app` tag. |
| `environment` (required) | e.g. `production`. |
| `release` | Version or git tag. |
| `umami` | `UmamiConfig(host, website_id, hostname)`. `hostname` is the API's real public hostname; Umami needs one to attribute events. Omit to disable events. |
| `glitchtip` | `GlitchTipConfig(dsn, sample_rate, traces_sample_rate)`. The DSN key has **no dashes**. Omit to disable errors. |
| `enabled` | Kill switch; `False` makes every call a no-op. Keep dev/test silent. |
| `sanitize_url` | Scrubs URLs, see below. |
| `before_track`, `before_send` | Inspect or drop events / errors (return `None` to drop). |
| `sentry_options` | Extra kwargs for `sentry_sdk.init` (integrations etc). |

## FastAPI

```python
import ambient_telemetry as at
from ambient_telemetry.starlette import TelemetryMiddleware

at.init(...)                              # once at startup, only in production
app.add_middleware(TelemetryMiddleware)   # reads X-Ambient-Session

async def current_user(...):              # an *async* dependency
    user = ...
    at.bind(user_id=str(user.id), org_id=str(user.org_id))
    return user
```

Add `X-Ambient-Session` to your CORS `allow_headers`, or browsers will block every request that carries it. Sentry's FastAPI/Starlette integrations turn on automatically and capture unhandled 5xx errors.

## Sessions and identity

- `bind(user_id=, org_id=, session_id=)` stores identity in a `contextvar` for the current request/task. Every `track` and `capture_error` after it carries it: the user id becomes Umami's distinct id (the same `identify` id the browser library uses) and Sentry's `user.id`; org and session ids go on as event data / tags.
- `ambient_telemetry.starlette.TelemetryMiddleware` reads the browser's `X-Ambient-Session` header, so a backend error shares a `session_id` with the frontend events that led to it.
- In FastAPI, bind from an **async** dependency (a sync dependency runs in a copied context and the binding is lost).
- Send internal ids only, never emails or names.

## Contract (same as the TS library)

`init`, `track`, `page`, `capture_error`, `identify`, `flush`. Nothing raises; calls before `init` are buffered (max 50) and replayed; `enabled=False` is a full no-op; keys like `password` and `token` are redacted; Umami requests send a browser-shaped `User-Agent` (Umami silently drops bot-looking ones with HTTP 200).

## Keeping URLs safe (`sanitize_url`)

Umami events carry a URL, and Sentry attaches request URLs to errors. If yours hold ids, names or one-time tokens, pass `sanitize_url` to `TelemetryConfig`. It is applied to the Umami `url` (`track(url=...)`, `page`, `identify`) and to the Sentry event's `request.url`, `Referer` header, stored query string, and breadcrumb `url` / `from` / `to` (plus `http.query` and `http.fragment`, which sentry-sdk stores separately). If it raises, the URL becomes `/`. Your own `sentry_options` `before_send` / `before_breadcrumb` still run, after the scrubber.

```python
import re

at.TelemetryConfig(
    ...,
    sanitize_url=lambda u: re.sub(r"/projects/[^/]+", "/projects/:id", u.split("?")[0]),
)
```

## Gotchas

- Umami answers `{"beep":"boop"}` with HTTP 200 and drops anything that looks like a bot. The default User-Agent is browser-shaped for that reason: do not override it.
- Umami events sent from a server have no visitor IP or browser of their own; they join the browser's session through the shared user id.

## Releasing

Tags are the release. Bump `version` in `pyproject.toml`, update `CHANGELOG.md`, run the checks below, commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z`. Consumers pin the tag.

## Development

```bash
uv sync && uv run pytest && uv run ruff check . && uv run mypy src
```
