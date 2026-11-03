# Changelog

## 0.3.0
- `capture_ip` (off by default): record the end user's public IP so events and errors can be filtered by it. Until now every server-side event and error carried the API server's own IP (Umami reads it from the connection; GlitchTip overwrites `user.ip_address` with the sender's IP).
- `bind(ip=)` / `bound(ip=)`, and `TelemetryMiddleware` binds it per request from the ASGI peer address (what uvicorn's `--proxy-headers` produces), or from a trusted proxy header via `TelemetryMiddleware(app, ip_header="cf-connecting-ip")`. Only public addresses are kept; private, loopback, CGNAT and junk values are ignored.
- With `capture_ip`: Umami events/pageviews/identify carry the IP (geo and session attribution now describe the user) plus a `client_ip` event property; every GlitchTip error, including unhandled 5xx captured by the Sentry integrations, gets a `client_ip` tag.

## 0.2.0
- `sanitize_url`: scrub URLs sent to Umami and attached to Sentry events (request url, Referer, query string, breadcrumbs incl. `http.query`/`http.fragment`). Same semantics as the TypeScript library's `sanitizeUrl`; fails closed to `/`.

## 0.1.2
- Docs only: config reference, FastAPI recipe, gotchas and known gaps (no `sanitize_url` yet), release steps.

## 0.1.1
- Browser-shaped default User-Agent so Umami doesn't drop server events.

## 0.1.0
- First release: `init`, `track`, `page`, `capture_error`, `identify`, `flush`, `bind`/`bound`, Starlette middleware.
