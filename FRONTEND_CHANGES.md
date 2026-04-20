# Frontend Improvements — Changelog

All changes are scoped to `frontends/`. The backend contract is untouched.

## Files

### New
- **`frontends/api.py`** — Shared HTTP client. Env-driven base URL, bearer auth,
  timeouts, retry-once on 5xx/connection errors, 401 → clean logout + rerun,
  uniform error surface via `APIError` + `safe_call`.
- **`frontends/ui.py`** — Shared UI helpers. Themed CSS, unified status badges,
  priority chips, inline file preview (images + PDFs), "next action" banner,
  chat history trimming.

### Rewritten
- **`frontends/_auth.py`** — Proper gating with `st.stop()`, login form inside
  an `st.form`, optional `require_roles=(...)` for page-level RBAC, retains
  last-used email, surfaces expired-session messages.
- **`frontends/app_onboarding.py`** — Uses shared api/ui, clear loading states
  via `st.status`, client-side file validation (size, type), typed toasts,
  catalog-backed hardware picker, trimmed chat history, HR rejection reasons
  rendered inline per step.
- **`frontends/app_offboarding.py`** — Same treatment: shared api/ui, typed
  toasts, date-picker now enforces `min_value=today`, trimmed chat history.
- **`frontends/app_hr.py`** — Major rework:
  - Inline preview for attachments (images inline, PDFs in iframe, lazy-load
    per file — no more N synchronous downloads on every rerun).
  - Auto-refresh (Off / 10s / 30s / 60s).
  - Robust dataframe that tolerates missing / null columns.
  - Multi-filter: status + flow + priority + free-text search.
  - Ticket-detail view separated from the queue with metadata, description
    banner, approvals, attachments section.
  - KPI cards + richer analytics tab (by flow, by status, avg resolution
    hours per step, rejection rate per step, SLA-risk table).

### Deleted
- **`frontends/onboarding_step1.py`**, **`onboarding_step2.py`**, **`onboarding_step3.py`**
  — Dead code. Never imported; logic lives inline in `app_onboarding.py`.
  `onboarding_step1.py` even referenced a response field (`agent_decision`)
  the backend never returns.

## Critical fixes

| # | Issue | Before | After |
|---|-------|--------|-------|
| 1 | Expired token leaves UI in a broken state | Silent 401 → opaque "service unavailable" | 401 clears session, shows expiry message on login form |
| 2 | Hardcoded API URL in 4 files | `API_URL = "http://localhost:8000"` repeated | Single `HR_API_URL` env var, default `localhost:8000` |
| 3 | HR file preview downloads all attachments on every rerun | N synchronous downloads per selected ticket | Lazy, per-file `Preview` / `Download` buttons; bytes cached |
| 4 | No timeouts on any request | Stalled backend freezes Streamlit thread forever | 60s default timeout, configurable via `HR_API_TIMEOUT` |
| 5 | Unbounded chat history sent to backend | Grows forever, blows up LLM context | Trimmed to last 10 turns per request |
| 6 | Fragile dataframe handling | `df['status'].unique()` crashes on empty/null | Defensive column existence + fillna throughout |
| 7 | Access-denied check only for HR page | Manual check in app_hr.py | `check_auth(require_roles=("hr","admin"))` reusable |

## Environment variables

```
HR_API_URL       # default: http://localhost:8000
HR_API_TIMEOUT   # default: 60 (seconds)
```

## Running

Identical to before — the command surface is unchanged:

```bash
streamlit run frontends/app_onboarding.py --server.port 8501
streamlit run frontends/app_offboarding.py --server.port 8502
streamlit run frontends/app_hr.py --server.port 8503
```

Optionally point at a non-local backend:

```bash
HR_API_URL=https://hr-api.example.com streamlit run frontends/app_hr.py
```
