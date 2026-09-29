# Changelog

## 0.2.0
- `sanitize_url`: scrub URLs sent to Umami and attached to Sentry events (request url, Referer, query string, breadcrumbs incl. `http.query`/`http.fragment`). Same semantics as the TypeScript library's `sanitizeUrl`; fails closed to `/`.

## 0.1.2
- Docs only: config reference, FastAPI recipe, gotchas and known gaps (no `sanitize_url` yet), release steps.

## 0.1.1
- Browser-shaped default User-Agent so Umami doesn't drop server events.

## 0.1.0
- First release: `init`, `track`, `page`, `capture_error`, `identify`, `flush`, `bind`/`bound`, Starlette middleware.
