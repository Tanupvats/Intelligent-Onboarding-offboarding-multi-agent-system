"""
Shared UI helpers for the Streamlit frontends:
- Unified status badges
- A light theming pass (custom CSS)
- Inline file preview (image/PDF) for HR review
- "Next action" banner
"""

from __future__ import annotations

import base64
import os
from typing import Dict, Iterable, List, Optional

import streamlit as st

from api import get_file, APIError


# --- Theme -----------------------------------------------------------------

_THEME_CSS = """
<style>
/* Tighten default Streamlit padding */
.block-container { padding-top: 2rem; padding-bottom: 2rem; }

/* Step cards */
.hr-card {
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 12px;
    padding: 1rem 1.25rem;
    background: var(--background-color, #ffffff);
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    height: 100%;
}
.hr-card h4 { margin-top: 0; margin-bottom: 0.25rem; }

/* Badges */
.hr-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.80rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    line-height: 1.4;
    border: 1px solid transparent;
}
.hr-badge--completed   { background:#e6f7ec; color:#146c2e; border-color:#b7e1c3; }
.hr-badge--pending     { background:#fff6e0; color:#8a5a00; border-color:#f0d89a; }
.hr-badge--unlocked    { background:#e6efff; color:#1a4fb0; border-color:#b3cdf7; }
.hr-badge--rejected    { background:#fde7e9; color:#a01a27; border-color:#f4b4ba; }
.hr-badge--locked      { background:#eef0f3; color:#555;    border-color:#d6d9de; }
.hr-badge--approved    { background:#e6f7ec; color:#146c2e; border-color:#b7e1c3; }
.hr-badge--open        { background:#e6efff; color:#1a4fb0; border-color:#b3cdf7; }
.hr-badge--blocked     { background:#fde7e9; color:#a01a27; border-color:#f4b4ba; }
.hr-badge--done        { background:#e6f7ec; color:#146c2e; border-color:#b7e1c3; }
.hr-badge--closed      { background:#eef0f3; color:#555;    border-color:#d6d9de; }

/* Priority chips */
.hr-prio { font-size:0.75rem; font-weight:600; padding:2px 8px; border-radius:6px; }
.hr-prio--P1 { background:#fde7e9; color:#a01a27; }
.hr-prio--P2 { background:#fff6e0; color:#8a5a00; }
.hr-prio--P3 { background:#eef0f3; color:#555; }

/* Next action banner */
.hr-next {
    border-left: 4px solid #1a4fb0;
    background: #f4f7fe;
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 1rem;
}

/* Reduce the gap between form controls */
div[data-testid="stVerticalBlock"] > div:has(> .hr-card) { height: 100%; }
</style>
"""


def inject_theme() -> None:
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


# --- Badges ----------------------------------------------------------------

_PROGRESS_BADGE_LABEL = {
    "completed":  "Completed",
    "pending_hr": "Pending HR Review",
    "unlocked":   "Action Required",
    "rejected":   "Needs Resubmission",
    "locked":     "Locked",
}


def progress_badge(status: str) -> str:
    """Badge HTML for the candidate/employee portals (step-level status)."""
    key = (status or "locked").lower()
    label = _PROGRESS_BADGE_LABEL.get(key, key.replace("_", " ").title())
    klass = key if key in _PROGRESS_BADGE_LABEL else "locked"
    return f'<span class="hr-badge hr-badge--{klass}">{label}</span>'


def ticket_status_badge(status: str) -> str:
    """Badge HTML for HR ticket statuses."""
    key = (status or "open").lower()
    known = {"open", "pending", "approved", "rejected", "done", "closed", "blocked"}
    klass = key if key in known else "open"
    label = key.capitalize()
    return f'<span class="hr-badge hr-badge--{klass}">{label}</span>'


def priority_chip(priority: str) -> str:
    p = (priority or "").upper()
    if p not in ("P1", "P2", "P3"):
        return ""
    return f'<span class="hr-prio hr-prio--{p}">{p}</span>'


# --- Next-action helpers ---------------------------------------------------

ONBOARDING_STEPS = [
    ("step1", "Review & respond to your offer letter", "Step 1: Offer Letter"),
    ("step2", "Upload your verification documents",    "Step 2: Document Verification"),
    ("step3", "Choose your IT hardware",                "Step 3: IT Hardware Provisioning"),
]
OFFBOARDING_STEPS = [
    ("step1", "Initiate your separation",             "Step 1: Initiation"),
    ("step2", "Await HR/manager approval",            "Step 2: HR Approval"),
    ("step3", "Confirm your last working day",        "Step 3: Exit Formalities"),
]


def next_action_banner(progress: Dict, flow: str) -> Optional[str]:
    """Return the 'Current step' label for chat context and render a banner."""
    steps = ONBOARDING_STEPS if flow == "onboarding" else OFFBOARDING_STEPS

    current_step_label: Optional[str] = None
    for key, action, label in steps:
        status = (progress.get(key) or "locked").lower()
        if status in ("unlocked", "rejected"):
            current_step_label = label
            icon = "🔓" if status == "unlocked" else "♻️"
            msg = "Please " + action.lower()
            if status == "rejected":
                msg += " — your previous submission needs attention."
            st.markdown(
                f'<div class="hr-next"><strong>{icon} Next action:</strong> {msg}</div>',
                unsafe_allow_html=True,
            )
            return label
        if status == "pending_hr":
            current_step_label = label
            st.markdown(
                f'<div class="hr-next"><strong>⏳ Pending HR review:</strong> '
                f"Your {label.split(':', 1)[-1].strip().lower()} is with our HR team. "
                "We'll email you when there's an update.</div>",
                unsafe_allow_html=True,
            )
            return label

    # All done
    if (progress.get("step3") or "").lower() == "completed":
        current_step_label = f"{flow.capitalize()} Completed"
    return current_step_label


# --- Inline file preview ---------------------------------------------------

_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_PDF_EXT = {".pdf"}


def _split_attachments(attachments: str) -> List[str]:
    if not attachments:
        return []
    return [p.strip() for p in attachments.split(";") if p.strip()]


def render_attachments(attachments: str, key_prefix: str = "att") -> None:
    """
    Render a list of attachment paths with lazy, per-file previews.
    Each file shows name + size + a 'Preview' expander that fetches on demand,
    plus a download button. Images render inline; PDFs render in an iframe.
    """
    paths = _split_attachments(attachments)
    if not paths:
        st.caption("No attachments.")
        return

    st.markdown(f"**📎 {len(paths)} attachment(s)**")
    for idx, path in enumerate(paths):
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        state_key = f"{key_prefix}_loaded_{idx}"

        with st.expander(f"📄 {name}", expanded=False):
            col_a, col_b = st.columns([1, 1])
            with col_a:
                preview_clicked = st.button(
                    "👁️ Preview", key=f"{key_prefix}_prev_{idx}", use_container_width=True
                )
            with col_b:
                download_clicked = st.button(
                    "⬇️ Download", key=f"{key_prefix}_dl_{idx}", use_container_width=True
                )

            if preview_clicked or download_clicked or st.session_state.get(state_key):
                if not st.session_state.get(state_key):
                    try:
                        content, content_type = get_file(path)
                        st.session_state[state_key] = (content, content_type)
                    except APIError as e:
                        st.error(f"Couldn't load file: {e.message}")
                        continue

                content, content_type = st.session_state[state_key]

                if download_clicked:
                    st.download_button(
                        "Click to save",
                        data=content,
                        file_name=name,
                        mime=content_type,
                        key=f"{key_prefix}_save_{idx}",
                    )

                if preview_clicked or st.session_state.get(f"{key_prefix}_showprev_{idx}"):
                    st.session_state[f"{key_prefix}_showprev_{idx}"] = True
                    if ext in _IMAGE_EXT:
                        st.image(content, caption=name, use_container_width=True)
                    elif ext in _PDF_EXT:
                        b64 = base64.b64encode(content).decode("utf-8")
                        st.markdown(
                            f'<iframe src="data:application/pdf;base64,{b64}" '
                            f'width="100%" height="600" style="border:1px solid #ddd;'
                            f'border-radius:6px;"></iframe>',
                            unsafe_allow_html=True,
                        )
                        st.caption(
                            "If the inline PDF doesn't render, use the Download button above."
                        )
                    else:
                        st.info(
                            f"No inline preview for `.{ext.lstrip('.')}` files — please download."
                        )
                        st.caption(f"Size: {_format_size(len(content))}")


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --- Small utilities -------------------------------------------------------

def trim_chat_history(history: List[Dict], max_turns: int = 10) -> List[Dict]:
    """Keep at most `max_turns` most recent exchanges (2 messages per turn)."""
    limit = max_turns * 2
    if len(history) <= limit:
        return history
    # Always keep the first assistant greeting if present
    head = history[:1] if history and history[0].get("role") == "assistant" else []
    tail = history[-limit:]
    return head + tail if head and head[0] not in tail else tail
