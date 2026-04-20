"""
Candidate Onboarding Portal — improved.

Highlights vs original:
- Uses shared api client (auth, timeouts, 401 logout, retries)
- Progress fetch is cached briefly to avoid refetching on every widget change
- Status badges use a unified styled component
- "Next action" banner tells the user exactly what to do
- Real loading / error states, file size + type validation
- Chat: trimmed history, clear-chat button, backend-aware current_step
- No hardcoded API URL, no request without timeout
"""

from __future__ import annotations

import os
from typing import List

import streamlit as st

from _auth import check_auth, logout
from api import APIError, get_json, post_json, request, safe_call
from ui import (
    ONBOARDING_STEPS,
    inject_theme,
    next_action_banner,
    progress_badge,
    trim_chat_history,
)

MAX_UPLOAD_MB = 10
ALLOWED_UPLOAD_TYPES = ["pdf", "jpg", "jpeg", "png"]
LAPTOP_CATALOG = [
    "MacBook Pro 14-inch",
    "MacBook Air M3",
    "Windows ThinkPad T14",
    "Dell XPS 15",
]
ACCESSORY_CATALOG = [
    "External 27-inch Monitor",
    "Wireless Mouse",
    "Mechanical Keyboard",
    "Noise-Cancelling Headset",
]


st.set_page_config(page_title="Candidate Onboarding", layout="wide", page_icon="🎯")
inject_theme()
check_auth(login_title="Welcome to Onboarding")
profile = st.session_state["profile"]


# --- Session-state defaults ------------------------------------------------
st.session_state.setdefault("active_step", None)
st.session_state.setdefault(
    "chat_history_onb",
    [
        {
            "role": "assistant",
            "content": (
                f"Hi {profile.get('name', 'there')}! I'm your AI HR Guide. "
                "Ask me anything about your onboarding — offer letter, documents, or IT assets."
            ),
        }
    ],
)


# --- Progress fetch --------------------------------------------------------
@st.cache_data(ttl=5, show_spinner=False)
def _fetch_progress(token: str):
    # token included to invalidate cache on login change
    return get_json("/progress/onboarding")


try:
    progress = _fetch_progress(st.session_state["token"]) or {}
except APIError as e:
    st.error(f"Couldn't load your onboarding status: {e.message}")
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
            st.session_state["active_step"] = None
            st.rerun()

    st.divider()
    st.subheader("💬 HR Support")

    if st.button("🧹 Clear chat", use_container_width=True):
        st.session_state["chat_history_onb"] = [
            {
                "role": "assistant",
                "content": f"Hi again {profile.get('name', 'there')}! What can I help with?",
            }
        ]
        st.rerun()

    chat_container = st.container(height=400)
    for msg in st.session_state["chat_history_onb"]:
        chat_container.chat_message(msg["role"]).write(msg["content"])

    prompt = st.chat_input("Ask about onboarding...")


# --- Title + next-action banner + step cards ------------------------------
st.title("Onboarding Portal")

current_step_label = next_action_banner(progress, "onboarding") or "General Onboarding"

cols = st.columns(3, gap="medium")
for (key, _, label), col in zip(ONBOARDING_STEPS, cols):
    status = (progress.get(key) or "locked").lower()
    with col:
        with st.container(border=True):
            st.markdown(f"#### {label}")
            st.markdown(progress_badge(status), unsafe_allow_html=True)

            # Show rejection reason if the step was rejected
            if status == "rejected":
                ticket = (progress.get("tickets") or {}).get(key) or {}
                if ticket.get("comments") or ticket.get("description"):
                    st.caption(
                        f"**HR note:** {ticket.get('comments') or ticket.get('description')}"
                    )

            # Action button
            btn_label = {
                "step1": "Review Offer",
                "step2": "Upload Documents",
                "step3": "Select Hardware",
            }[key]
            step_idx = {"step1": 1, "step2": 2, "step3": 3}[key]
            disabled = status not in ("unlocked", "rejected")
            if st.button(
                btn_label,
                key=f"btn_{key}",
                use_container_width=True,
                disabled=disabled,
                type="primary" if status in ("unlocked", "rejected") else "secondary",
            ):
                st.session_state["active_step"] = step_idx
                st.rerun()

st.divider()


# --- Active-step panels ---------------------------------------------------
def _close_active_step():
    st.session_state["active_step"] = None
    st.cache_data.clear()
    st.rerun()


active = st.session_state["active_step"]

if active is None:
    if (progress.get("step3") or "").lower() == "completed":
        st.success(
            "🎉 You've completed all onboarding steps! "
            "HR will contact you shortly with your start date."
        )
        st.balloons()
    else:
        st.info("Select a step above to continue.")

elif active == 1:
    st.header("Step 1 · Offer Letter Review")
    st.info(
        f"**Position:** {profile.get('role', '—')}  |  "
        f"**Department:** {profile.get('department', '—')}"
    )
    dec = st.radio(
        "Do you accept this offer?",
        ("Yes, I accept", "No, I need to negotiate"),
        horizontal=True,
    )
    reason = ""
    if dec == "No, I need to negotiate":
        reason = st.text_area(
            "Please detail your concerns:",
            placeholder="e.g., salary, start date, benefits...",
            height=120,
        )

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Decision", type="primary", use_container_width=True):
            if dec.startswith("No") and not reason.strip():
                st.warning("Please explain your concerns before submitting.")
            else:
                ok, _ = safe_call(
                    post_json,
                    "/onboarding/offer",
                    json={"accepted": dec == "Yes, I accept", "reason": reason},
                    spinner="Notifying HR agent...",
                    error_prefix="Couldn't submit your decision",
                )
                if ok:
                    st.toast("Decision submitted ✔", icon="✅")
                    _close_active_step()
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()

elif active == 2:
    st.header("Step 2 · Document Verification")

    if (progress.get("step2") or "").lower() == "rejected":
        prev = (progress.get("tickets") or {}).get("step2") or {}
        st.error(
            "**Previous upload was rejected.** "
            f"{prev.get('comments') or prev.get('description') or 'Documents did not meet compliance standards.'}"
        )

    st.caption(
        f"Accepted formats: **{', '.join(ALLOWED_UPLOAD_TYPES).upper()}** · "
        f"Max size per file: **{MAX_UPLOAD_MB} MB**"
    )
    docs = st.file_uploader(
        "Upload Government ID & supporting documents",
        accept_multiple_files=True,
        type=ALLOWED_UPLOAD_TYPES,
    )

    # Client-side validation
    oversize: List[str] = []
    total_size = 0
    if docs:
        for f in docs:
            size = len(f.getvalue())
            total_size += size
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                oversize.append(f.name)
        st.caption(f"Selected **{len(docs)}** file(s), total **{total_size / (1024*1024):.1f} MB**.")

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Documents", type="primary", use_container_width=True):
            if not docs:
                st.warning("Please attach at least one file.")
            elif oversize:
                st.error(f"These files exceed {MAX_UPLOAD_MB}MB: {', '.join(oversize)}")
            else:
                files_payload = [("files", (f.name, f.getvalue(), f.type)) for f in docs]
                try:
                    with st.status("Uploading and running AI pre-check...", expanded=True) as s:
                        s.write("📤 Uploading files to secure storage...")
                        request("POST", "/onboarding/documents", files=files_payload, timeout=120)
                        s.write("🤖 AI agents validating documents...")
                        s.update(label="Submitted!", state="complete")
                    st.toast("Documents submitted for HR review ✔", icon="📨")
                    _close_active_step()
                except APIError as e:
                    st.error(f"Upload failed: {e.message}")
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()

elif active == 3:
    st.header("Step 3 · IT Hardware Provisioning")
    col1, col2 = st.columns(2)
    with col1:
        lap = st.selectbox("Primary device", LAPTOP_CATALOG)
    with col2:
        acc = st.multiselect("Peripherals", ACCESSORY_CATALOG)

    st.caption("Your selection is subject to department policy review.")

    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Request Assets", type="primary", use_container_width=True):
            ok, _ = safe_call(
                post_json,
                "/onboarding/assets",
                json={"laptop_type": lap, "accessories": acc},
                spinner="Running IT policy check...",
                error_prefix="Couldn't submit your asset request",
            )
            if ok:
                st.toast("Asset request submitted ✔", icon="💻")
                _close_active_step()
    with col_cancel:
        if st.button("Cancel"):
            _close_active_step()


# --- Chat handler (after main body so progress is already resolved) -------
if prompt:
    st.session_state["chat_history_onb"].append({"role": "user", "content": prompt})

    # Trim to avoid unbounded context
    trimmed = trim_chat_history(st.session_state["chat_history_onb"], max_turns=10)

    with chat_container.chat_message("user"):
        st.write(prompt)
    with chat_container.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                resp = post_json(
                    "/chat",
                    json={
                        "message": prompt,
                        "flow": "onboarding",
                        "current_step": current_step_label,
                        "history": trimmed[:-1],  # exclude the just-added user msg
                    },
                )
                reply = (resp or {}).get("reply") or "Sorry, I couldn't generate a response."
            except APIError as e:
                reply = f"⚠️ Chat service error: {e.message}"

            st.write(reply)
            st.session_state["chat_history_onb"].append(
                {"role": "assistant", "content": reply}
            )
    st.rerun()
