"""
Shared HTTP client for the Streamlit frontends.

Centralizes:
- API base URL (env-driven)
- Bearer-auth injection
- Sensible timeouts
- Retry-once on transient 5xx / connection errors
- 401 handling -> force clean logout (expired token)
- Uniform error surfacing to the Streamlit user
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import requests
import streamlit as st

API_URL = os.getenv("HR_API_URL", "http://localhost:8000").rstrip("/")
DEFAULT_TIMEOUT = float(os.getenv("HR_API_TIMEOUT", "60"))  # agent calls can be slow


class APIError(Exception):
    """Raised when the backend returns a non-2xx we cannot silently retry."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload


def _auth_headers() -> Dict[str, str]:
    token = st.session_state.get("token")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _force_logout(reason: str = "Your session has expired. Please log in again.") -> None:
    """Clear auth state and prompt re-login. Called on 401."""
    for k in ("token", "profile"):
        st.session_state.pop(k, None)
    st.session_state["_auth_error"] = reason
    st.rerun()


def _should_retry(exc: Optional[Exception], status_code: Optional[int]) -> bool:
    if exc is not None and isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if status_code is not None and status_code in (502, 503, 504):
        return True
    return False


def request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: Dict[str, Any] | None = None,
    files: Any = None,
    data: Any = None,
    timeout: float | None = None,
    auth: bool = True,
    expect_json: bool = True,
    max_retries: int = 1,
) -> Tuple[int, Any, Dict[str, str]]:
    """
    Low-level request helper. Returns (status_code, body, headers).

    - `auth=True` attaches Bearer token from session_state.
    - On 401, clears session and triggers a rerun (never returns).
    - Retries once on connection errors / 5xx.
    - Raises APIError on final non-2xx (except 401, which logs out).
    """
    url = f"{API_URL}{path if path.startswith('/') else '/' + path}"
    headers = _auth_headers() if auth else {}
    t = timeout if timeout is not None else DEFAULT_TIMEOUT

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(
                method.upper(),
                url,
                json=json,
                params=params,
                files=files,
                data=data,
                headers=headers,
                timeout=t,
            )
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            if attempt < max_retries and _should_retry(e, None):
                time.sleep(0.4 * (attempt + 1))
                continue
            raise APIError(0, f"Cannot reach backend at {API_URL}. {type(e).__name__}: {e}") from e

        if resp.status_code == 401 and auth:
            _force_logout()
            # _force_logout calls st.rerun(); execution will not continue past it
            return 401, None, {}

        if resp.status_code >= 500 and attempt < max_retries:
            time.sleep(0.4 * (attempt + 1))
            continue

        if resp.status_code >= 400:
            # Try to extract a useful message from FastAPI-style {detail: ...}
            detail: Any
            try:
                detail = resp.json()
                msg = detail.get("detail") if isinstance(detail, dict) else str(detail)
            except Exception:
                detail = resp.text
                msg = resp.text or resp.reason
            raise APIError(resp.status_code, str(msg) if msg else "Request failed", payload=detail)

        if expect_json:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
        else:
            body = resp.content

        return resp.status_code, body, dict(resp.headers)

    # Exhausted retries on transport errors
    raise APIError(0, f"Backend unreachable after retries. Last error: {last_exc}")


# --- Convenience helpers ---------------------------------------------------

def get_json(path: str, **kw) -> Any:
    _, body, _ = request("GET", path, **kw)
    return body


def post_json(path: str, json: Any = None, **kw) -> Any:
    _, body, _ = request("POST", path, json=json, **kw)
    return body


def get_file(path: str) -> Tuple[bytes, str]:
    """Returns (bytes, content_type) for a backend-served file."""
    _, body, headers = request(
        "GET", "/files/get", params={"path": path}, expect_json=False
    )
    return body, headers.get("Content-Type", "application/octet-stream")


def login(email: str, password: str) -> Dict[str, Any]:
    """Unauthenticated login call. Returns {token, profile}."""
    _, body, _ = request(
        "POST", "/auth/login", json={"email": email, "password": password}, auth=False
    )
    return body


# --- Streamlit-friendly error surface --------------------------------------

def safe_call(fn, *args, spinner: str | None = None, error_prefix: str = "Request failed", **kwargs):
    """
    Run an API call with a spinner and graceful error display.
    Returns (ok, result). If ok=False, an st.error was already shown.
    """
    try:
        if spinner:
            with st.spinner(spinner):
                return True, fn(*args, **kwargs)
        return True, fn(*args, **kwargs)
    except APIError as e:
        if e.status_code == 0:
            st.error(f"🔌 {error_prefix}: backend unreachable.\n\n*{e.message}*")
        elif e.status_code == 403:
            st.error("🚫 You don't have permission to perform this action.")
        elif e.status_code == 404:
            st.warning(f"Not found: {e.message}")
        elif 400 <= e.status_code < 500:
            st.error(f"⚠️ {error_prefix}: {e.message}")
        else:
            st.error(f"💥 Server error ({e.status_code}): {e.message}")
        return False, None
    except Exception as e:  # defensive
        st.error(f"Unexpected error: {e}")
        return False, None
