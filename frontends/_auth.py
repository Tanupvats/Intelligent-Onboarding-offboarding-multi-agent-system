"""
Shared authentication helpers for the Streamlit frontends.

Improvements over the original:
- Gates the page properly with st.stop()
- Uses the shared `api` client (timeouts, retries, 401 handling)
- Shows a friendly message when the previous session expired
- Remembers the last-entered email across refreshes in this browser tab
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

import streamlit as st

from api import APIError, login as api_login


def _login_form(title: str = "Enterprise Onboarding & Offboarding") -> None:
    st.markdown(
        f"<h1 style='text-align:center;margin-bottom:0.25rem;'>{title}</h1>"
        "<p style='text-align:center;color:#666;margin-top:0;'>"
        "Sign in to continue.</p>",
        unsafe_allow_html=True,
    )

    # Surface auth-related messages from previous interactions
    err = st.session_state.pop("_auth_error", None)
    if err:
        st.warning(err)

    _, col, _ = st.columns([1, 2, 1])
    with col:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input(
                "Email", value=st.session_state.get("_last_email", ""),
                placeholder="you@company.com",
            )
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Please enter both email and password.")
                return
            with st.spinner("Authenticating..."):
                try:
                    data = api_login(email.strip(), password)
                except APIError as e:
                    if e.status_code == 401:
                        st.error("Invalid credentials.")
                    elif e.status_code == 0:
                        st.error(
                            "Backend is unreachable. Please ensure the API is running "
                            f"and reachable. ({e.message})"
                        )
                    else:
                        st.error(f"Login failed: {e.message}")
                    return

            st.session_state["token"] = data.get("token")
            st.session_state["profile"] = data.get("profile", {})
            st.session_state["_last_email"] = email.strip()
            st.rerun()


def check_auth(
    *,
    require_roles: Optional[Iterable[str]] = None,
    login_title: str = "Enterprise Onboarding & Offboarding",
) -> None:
    """
    Gate this page. If the user is not logged in, show login and stop execution.
    If `require_roles` is set, check that the profile's role is in the allow-list;
    otherwise show an access-denied screen.
    """
    if "token" not in st.session_state or not st.session_state.get("token"):
        _login_form(login_title)
        st.stop()

    if require_roles:
        profile = st.session_state.get("profile") or {}
        role = (profile.get("role") or "").lower()
        allowed = {r.lower() for r in require_roles}
        if role not in allowed:
            st.error("🚫 Access denied — you don't have permission to view this page.")
            st.caption(f"Your role: `{role or 'unknown'}` · Required: `{', '.join(sorted(allowed))}`")
            if st.button("Logout"):
                logout()
            st.stop()


def logout() -> None:
    """Clear session and rerun to show the login form."""
    # Preserve last_email for convenience on the next login
    last_email = st.session_state.get("_last_email")
    st.session_state.clear()
    if last_email:
        st.session_state["_last_email"] = last_email
    st.rerun()
