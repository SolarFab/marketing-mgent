# API reference

The FastAPI backend auto-generates an OpenAPI spec.

## Live docs

Once the server is running:

- **Interactive UI (Swagger):** [`http://127.0.0.1:8000/docs`](http://127.0.0.1:8000/docs)
- **Alternative UI (ReDoc):** [`http://127.0.0.1:8000/redoc`](http://127.0.0.1:8000/redoc)
- **Raw OpenAPI JSON:** [`http://127.0.0.1:8000/openapi.json`](http://127.0.0.1:8000/openapi.json)

Every endpoint has a `summary` and a docstring; the auto-generated page is the authoritative reference.

## Endpoint map

Grouped by responsibility (all endpoints are documented in [`backend/app.py`](../backend/app.py)):

### Onboarding
- `POST /onboard` — start onboarding from a URL. Runs crawl → extract → seed_sources, then interrupts. Returns the draft profile + proposed sources.
- `POST /onboard/confirm` — persist the (possibly edited) profile + sources.

### Profile
- `GET /profile` — current company profile.
- `PUT /profile` — edit profile (incl. `content_mix`).

### Sources
- `GET /sources` — list active + proposed.
- `POST /sources` — user-adds a source by URL.
- `PATCH /sources/{id}` — pause or activate.
- `DELETE /sources/{id}` — unfollow.
- `POST /sources/discover` — trigger source discovery.
- `POST /sources/{id}/accept` — promote a proposed source to active.

### Content cycle
- `POST /cycle/run` — start a new cycle. Runs load_state → ideate → evaluate, interrupts before review.
- `GET /queue` — scored queue for a cycle.
- `POST /feedback` — approve/reject on one item with a reason code.
- `POST /cycle/finish_review` — resume the cycle: runs Learning + Write, interrupts before publish.
- `GET /drafts` — latest drafts.
- `POST /write` — regenerate drafts with a layout override.
- `POST /publish` — publish one channel from a cycle's drafts.

### Learning
- `GET /learning` — pending + confirmed rules + reason histogram.
- `POST /learning/confirm` — promote a pending rule.
- `POST /learning/dismiss` — dismiss a pending rule.
- `DELETE /learning/{rule}` — remove a confirmed rule.

### Analytics
- `GET /analytics/approval_rate` — approval rate per cycle.
- `GET /analytics/source_hit_rates` — per-source hit rate.
- `GET /analytics/reason_histogram` — reject reasons rolling window.
- `GET /analytics/underperformers` — sources flagged for review.

### Orchestrator
- `POST /chat` — the chat rail. Body: `{message, context?}`. Returns `{action, note, result, reply}`.

## Auth

None. Single-tenant sprint, meant to run on `127.0.0.1`. `company_id` defaults from `COMPANY_ID` in `.env`; every endpoint accepts an override in the request body or query string.

## CORS

Wide open (`*`) so the Next.js dev server can hit it without proxying. Tighten for production.

## Errors

- `404` — resource not found (e.g., no profile yet, no drafts for cycle).
- `400` — invalid request (bad `status`, missing fields).
- Everything else surfaces the exception message.

## OpenAPI examples

Because every request model is a Pydantic `BaseModel` with named fields, the auto-generated docs include:

- Full JSON schema per endpoint
- Try-it-out with a live server call
- Curl snippets

Point Postman / Insomnia at [`/openapi.json`](http://127.0.0.1:8000/openapi.json) to import all endpoints in one go.
