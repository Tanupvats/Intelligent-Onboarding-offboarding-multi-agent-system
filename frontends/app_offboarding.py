"""
Employee Offboarding Portal — improved.

Parallel improvements to app_onboarding.py:
- Shared api client with auth / timeout / retry / 401 handling
- Unified themed badges + next-action banner
- Real loading/error states, toasts on success
- Chat: trimmed history, clear-chat button
- No hardcoded API URL
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from _auth import check_auth, logout
from api import APIError, get_json, post_json, safe_call
from ui import (
    OFFBOARDING_STEPS,
    inject_theme,
    next_action_banner,
    progress_badge,
    trim_chat_history,
)


st.set_page_config(page_title="Employee Offboarding", layout="wide", page_icon="👋")
inject_theme()
check_auth(login_title="Employee Offboarding")
profile = st.session_state["profile"]


# --- Session-state defaults -----------------------------------------------
st.session_state.setdefault("active_step_off", None)
st.session_state.setdefault(
    "chat_history_off",
    [
        {
            "role": "assistant",
            "content": (
                f"Hi {profile.get('name', 'there')}. I'm here to help you through "
                "the offboarding process. What can I help with?"
            ),
        }
    ],
)


# --- Progress fetch --------------------------------------------------------
@st.cache_data(ttl=5, show_spinner=False)
def _fetch_progress(token: str):
    return get_json("/progress/offboarding")


try:
    progress = _fetch_progress(st.session_state["token"]) or {}
except APIError as e:
    st.error(f"Couldn't load your offboarding status: {e.message}")
    if st.button("Retry"):
        st.cache_data.clear()
        st.rerun()
    st.stop()


# --- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.markdown(f"### 👋 {profile.get('name', 'User')}")
    st.caption(
        f"**Role:** {profile.get('role', '—')}  \n"
        f"**Dept:** {profile.get('department', '—')}"
    )

    col_lo, col_ref = st.columns(2)
    with col_lo:
        if st.button("Logout", use_container_width=True):
            logout()
    with col_ref:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.session_state["active_step_off"] = None
            st.rerun()

    st.divider()
    st.subheader("💬 HR Support")

    if st.button("🧹 Clear chat", use_container_width=True):
        st.session_state["chat_history_off"] = [
            {
                "role": "assistant",
                "content": f"Hi again {profile.get('name', 'there')}! What can I help with?",
            }
        ]
        st.rerun()

    chat_container = st.container(height=400)
    for msg in st.session_state["chat_history_off"]:
        chat_container.chat_message(msg["role"]).write(msg["content"])

    prompt = st.chat_input("Ask about offboarding...")


# --- Main ------------------------------------------------------------------
st.title("Offboarding Portal")

current_step_label = next_action_banner(progress, "offboarding") or "General Offboarding"

cols = st.columns(3, gap="medium")
for (key, _, label), col in zip(OFFBOARDING_STEPS, cols):
    status = (progress.get(key) or "locked").lower()
    with col:
        with st.container(border=True):
            st.markdown(f"#### {label}")
            st.markdown(progress_badge(status), unsafe_allow_html=True)

            if status == "rejected":
                ticket = (progress.get("tickets") or {}).get(key) or {}
                if ticket.get("comments") or ticket.get("description"):
                    st.caption(
                        f"**HR note:** {ticket.get('comments') or ticket.get('description')}"
                    )

            btn_label = {
                "step1": "Start Offboarding",
                "step2": "Acknowledge",
                "step3": "Finalize Exit",
            }[key]
            step_idx = {"step1": 1, "step2": 2, "step3": 3}[key]
            disabled = status not in ("unlocked", "rejected")
            if st.button(
                btn_label,
                key=f"btn_off_{key}",
                use_container_width=True,
                disabled=disabled,
                type="primary" if status in ("unlocked", "rejected") else "secondary",
            ):
                st.session_state["active_step_off"] = step_idx
                st.rerun()

st.divider()


def _close_active_step():
    st.session_state["active_step_off"] = None
    st.cache_data.clear()
    st.rerun()


active = st.session_state["active_step_off"]

if active is None:
    if (progress.get("step3") or "").lower() == "completed":
        st.success(
            "Your offboarding process is complete. "
            "Please ensure all physical assets are returned to IT."
        )
    else:
        st.info("Select a step above to continue.")

elif active == 1:
    st.header("Step 1 · Initiate Separation")
    st.warning(
        "Submitting this form will officially notify your manager and the HR department."
    )
    reason = st.text_area(
        "Reason for leaving",
        placeholder="e.g., Better opportunity, Relocation, Personal reasons...",
        height=120,
    )
    early_release = st.checkbox("I am requesting an early release (waive notice period)")

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Resignation", type="primary", use_container_width=True):
            if not reason.strip():
                st.error("Please provide a reason for your departure.")
            else:
                ok, _ = safe_call(
                    post_json,
                    "/offboarding/initiate",
                    json={"reason": reason, "early_release": early_release},
                    spinner="Initiating offboarding sequence...",
                    error_prefix="Couldn't initiate offboarding",
                )
                if ok:
                    st.toast("Resignation submitted ✔", icon="📩")
                    _close_active_step()
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()

elif active == 2:
    st.header("Step 2 · Pending HR & Manager Approval")
    st.info("Your separation request requires manual approval from HR.")
    st.caption(
        "Clicking acknowledge simply confirms that you understand the process is "
        "with HR — no further action is needed from you right now."
    )

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Acknowledge Wait", type="primary", use_container_width=True):
            ok, _ = safe_call(
                post_json,
                "/offboarding/approval",
                json=None,
                spinner="Updating status...",
                error_prefix="Couldn't acknowledge",
            )
            if ok:
                st.toast("Acknowledged ✔", icon="✅")
                _close_active_step()
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()

elif active == 3:
    st.header("Step 3 · Exit Formalities")
    st.write("Please confirm your final working day to generate your clearance checklist.")

    today = date.today()
    last_day = st.date_input(
        "Confirmed Last Working Day",
        value=today + timedelta(days=30),
        min_value=today,
    )

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Finalize Exit Plan", type="primary", use_container_width=True):
            ok, _ = safe_call(
                post_json,
                "/offboarding/exit",
                json={"last_day": last_day.strftime("%Y-%m-%d")},
                spinner="Generating clearance tickets...",
                error_prefix="Couldn't finalize exit plan",
            )
            if ok:
                st.toast("Exit plan generated ✔", icon="📋")
                _close_active_step()
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()


# --- Chat handler ---------------------------------------------------------
if prompt:
    st.session_state["chat_history_off"].append({"role": "user", "content": prompt})
    trimmed = trim_chat_history(st.session_state["chat_history_off"], max_turns=10)

    with chat_container.chat_message("user"):
        st.write(prompt)
    with chat_container.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = post_json(
                    "/chat",
                    json={
                        "message": prompt,
                        "flow": "offboarding",
                        "current_step": current_step_label,
                        "history": trimmed[:-1],
                    },
                )
                reply = (resp or {}).get("reply") or "Sorry, I couldn't generate a response."
            except APIError as e:
                reply = f"⚠️ Chat service error: {e.message}"

            st.write(reply)
            st.session_state["chat_history_off"].append(
                {"role": "assistant", "content": reply}
            )
    st.rerun()
