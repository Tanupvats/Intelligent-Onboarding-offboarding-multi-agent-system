"""
HR Control Center — improved.

Highlights vs original:
- Shared api client (auth, timeout, retry, 401 handling)
- Inline previews for attachments (images render inline, PDFs in iframe)
- Auto-refresh option (10/30/60s) for the ticket queue
- Ticket detail split from the dataframe for clarity
- KPI cards, per-flow breakdown, avg resolution time, SLA-risk surface
- Ticket update flow with clearer state + post-update confirmation
- Robust against malformed CSV data (missing columns / null statuses)
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

from _auth import check_auth, logout
from api import APIError, get_json, post_json, safe_call
from ui import (
    inject_theme,
    priority_chip,
    render_attachments,
    ticket_status_badge,
)


st.set_page_config(page_title="HR Ops Dashboard", layout="wide", page_icon="🎛️")
inject_theme()
check_auth(require_roles=("hr", "admin"), login_title="HR Control Center")
profile = st.session_state["profile"]


# --- Data fetch helpers ----------------------------------------------------

def _tickets_df(tickets: List[Dict[str, Any]]) -> pd.DataFrame:
    """Build a robust dataframe even if some columns are missing."""
    df = pd.DataFrame(tickets or [])
    expected = [
        "ticket_id", "type", "flow", "step", "employee_id", "employee_name",
        "department", "manager", "status", "priority", "created_at",
        "updated_at", "description", "assigned_to", "sla_due", "comments",
        "approvals", "attachments",
    ]
    for c in expected:
        if c not in df.columns:
            df[c] = ""
    # Normalize strings
    for c in ("status", "flow", "priority"):
        df[c] = df[c].fillna("").astype(str)
    # Parse dates (best-effort)
    for c in ("created_at", "updated_at"):
        df[c + "_dt"] = pd.to_datetime(df[c], errors="coerce")
    return df


@st.cache_data(ttl=10, show_spinner=False)
def _fetch_tickets(token: str) -> List[Dict[str, Any]]:
    resp = get_json("/tickets") or {}
    return resp.get("tickets", []) or []


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_employees(token: str) -> List[Dict[str, Any]]:
    resp = get_json("/employees") or {}
    return resp.get("employees", []) or []


def _format_ticket_option(df: pd.DataFrame, tid: str) -> str:
    row = df[df["ticket_id"] == tid].iloc[0]
    return (
        f"{tid}  ·  {row.get('employee_name', '—')}  ·  "
        f"{row.get('step', '—')}  ·  {row.get('status', '—')}"
    )


# --- Sidebar ---------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🎛️ HR Control Center")
    st.caption(f"**Operator:** {profile.get('name', 'HR')}")
    st.caption(f"**Role:** {profile.get('role', '—')}")

    col_lo, col_ref = st.columns(2)
    with col_lo:
        if st.button("Logout", use_container_width=True):
            logout()
    with col_ref:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.divider()
    st.markdown("**Live updates**")
    auto_refresh = st.selectbox(
        "Auto-refresh",
        options=["Off", "10s", "30s", "60s"],
        index=0,
        help="Automatically reload tickets on an interval.",
    )
    if auto_refresh != "Off":
        secs = int(auto_refresh.rstrip("s"))
        # st.autorefresh is available in modern Streamlit; fall back gracefully
        autofn = getattr(st, "autorefresh", None)
        if callable(autofn):
            autofn(interval=secs * 1000, key="hr_auto_refresh")
        else:
            st.caption("⚠️ Your Streamlit version doesn't support `st.autorefresh`.")


# --- Load tickets (with error handling) -----------------------------------
try:
    tickets = _fetch_tickets(st.session_state["token"])
except APIError as e:
    st.error(f"Couldn't load tickets: {e.message}")
    if st.button("Retry"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

df_all = _tickets_df(tickets)


# --- Top KPIs --------------------------------------------------------------
st.title("HR Operations Dashboard")

k1, k2, k3, k4 = st.columns(4)
total = len(df_all)
open_like = df_all["status"].str.lower().isin(["open", "pending"]).sum()
rejected_like = df_all["status"].str.lower().isin(["rejected", "blocked"]).sum()
done_like = df_all["status"].str.lower().isin(["done", "closed", "approved"]).sum()

k1.metric("Total tickets", total)
k2.metric("Needs attention", int(open_like + rejected_like))
k3.metric("Completed", int(done_like))
k4.metric(
    "Completion rate",
    f"{(done_like / total * 100):.0f}%" if total else "—",
)

st.divider()


# --- Tabs ------------------------------------------------------------------
tab_queue, tab_directory, tab_analytics = st.tabs(
    ["🎫 Ticket Queue", "👥 Employee Directory", "📊 Analytics"]
)


# =========================================================================
# TAB 1 — Ticket Queue
# =========================================================================
with tab_queue:
    st.subheader("Active workflows & agent exceptions")

    if df_all.empty:
        st.info("No tickets yet. The MAS queue is empty.")
    else:
        # --- Filters ------------------------------------------------------
        fcol1, fcol2, fcol3, fcol4 = st.columns([2, 2, 2, 2])

        all_statuses = sorted(s for s in df_all["status"].unique() if s)
        default_statuses = [
            s for s in all_statuses
            if s.lower() in ("open", "pending", "blocked", "rejected")
        ] or all_statuses

        with fcol1:
            status_filter = st.multiselect(
                "Status", all_statuses, default=default_statuses
            )
        with fcol2:
            flow_opts = sorted(f for f in df_all["flow"].unique() if f)
            flow_filter = st.multiselect("Flow", flow_opts, default=flow_opts)
        with fcol3:
            prio_opts = sorted(p for p in df_all["priority"].unique() if p)
            prio_filter = st.multiselect(
                "Priority", prio_opts, default=prio_opts
            )
        with fcol4:
            search = st.text_input(
                "Search", placeholder="Employee name, ticket ID, description..."
            )

        filtered = df_all[
            df_all["status"].isin(status_filter)
            & df_all["flow"].isin(flow_filter)
        ]
        if prio_opts and prio_filter:
            filtered = filtered[filtered["priority"].isin(prio_filter)]
        if search:
            s = search.strip().lower()
            mask = (
                filtered["ticket_id"].astype(str).str.lower().str.contains(s, na=False)
                | filtered["employee_name"].astype(str).str.lower().str.contains(s, na=False)
                | filtered["description"].astype(str).str.lower().str.contains(s, na=False)
            )
            filtered = filtered[mask]

        st.caption(f"Showing **{len(filtered)}** of {len(df_all)} tickets.")

        display_cols = [
            "ticket_id", "flow", "step", "employee_name",
            "status", "priority", "assigned_to", "updated_at", "description",
        ]
        # Only include columns that exist
        display_cols = [c for c in display_cols if c in filtered.columns]

        st.dataframe(
            filtered[display_cols] if not filtered.empty else filtered,
            use_container_width=True,
            hide_index=True,
            height=350,
        )

        st.divider()

        # --- Ticket detail + update --------------------------------------
        st.subheader("Review & update a ticket")

        if filtered.empty:
            st.caption("Adjust filters to see tickets here.")
        else:
            ticket_ids = filtered["ticket_id"].tolist()
            default_idx = 0
            selected_ticket_id = st.selectbox(
                "Select ticket",
                ticket_ids,
                index=default_idx,
                format_func=lambda tid: _format_ticket_option(
                    filtered, tid
                ),
            )

            t_detail: Dict[str, Any] = next(
                (t for t in tickets if t.get("ticket_id") == selected_ticket_id),
                {},
            )

            # Header row for the selected ticket
            h1, h2, h3 = st.columns([3, 1, 1])
            with h1:
                st.markdown(
                    f"### Ticket `{t_detail.get('ticket_id', '—')}` — "
                    f"{t_detail.get('flow', '').title()} · "
                    f"{t_detail.get('step', '').title()}"
                )
                st.caption(
                    f"**Employee:** {t_detail.get('employee_name', '—')} "
                    f"({t_detail.get('employee_id', '—')}) · "
                    f"**Dept:** {t_detail.get('department') or '—'} · "
                    f"**Manager:** {t_detail.get('manager') or '—'}"
                )
            with h2:
                st.markdown(
                    ticket_status_badge(t_detail.get("status", "")),
                    unsafe_allow_html=True,
                )
            with h3:
                chip = priority_chip(t_detail.get("priority", ""))
                if chip:
                    st.markdown(chip, unsafe_allow_html=True)

            if t_detail.get("description"):
                st.info(t_detail["description"])

            meta_cols = st.columns(3)
            meta_cols[0].caption(f"**Created:** {t_detail.get('created_at') or '—'}")
            meta_cols[1].caption(f"**Updated:** {t_detail.get('updated_at') or '—'}")
            meta_cols[2].caption(f"**SLA due:** {t_detail.get('sla_due') or '—'}")

            # Attachments
            atts = t_detail.get("attachments") or ""
            if atts:
                st.markdown("#### 📎 Attachments")
                render_attachments(atts, key_prefix=f"t_{selected_ticket_id}")

            # Update form
            st.markdown("#### ✏️ Update ticket")
            with st.form(f"update_form_{selected_ticket_id}", clear_on_submit=False):
                c1, c2 = st.columns(2)
                with c1:
                    status_options = [
                        "Open", "Pending", "Approved", "Rejected", "Done", "Closed", "Blocked",
                    ]
                    current_status = (t_detail.get("status") or "Open").capitalize()
                    default_idx = (
                        status_options.index(current_status)
                        if current_status in status_options else 0
                    )
                    new_status = st.selectbox("Status", status_options, index=default_idx)
                    new_assignee = st.text_input(
                        "Assigned to", value=t_detail.get("assigned_to", "")
                    )
                with c2:
                    comments = st.text_area(
                        "HR comments / override reason",
                        value=t_detail.get("comments", ""),
                        height=100,
                    )
                    notify_email = st.text_input(
                        "Notify employee email (optional)",
                        placeholder="Leave blank to use default",
                    )

                send_email = st.checkbox(
                    "Send AI-drafted notification email", value=True,
                    help=(
                        "If checked, the backend will draft a formal email via the "
                        "agent and send it through the MCP SMTP subprocess."
                    ),
                )
                submitted = st.form_submit_button(
                    "💾 Update ticket", type="primary", use_container_width=True
                )

            if submitted:
                payload = {
                    "ticket_id": selected_ticket_id,
                    "status": new_status,
                    "assigned_to": new_assignee,
                    "comments": comments,
                    # Backend sends email whenever the ticket updates successfully;
                    # leave email blank to suppress explicit override
                    "email": notify_email if send_email else "",
                }
                with st.status("Pushing update to MAS...", expanded=False) as s:
                    try:
                        s.write("📝 Persisting ticket update...")
                        resp = post_json("/tickets/update", json=payload)
                        if send_email:
                            s.write("📧 Agent is drafting the notification email...")
                            s.write(
                                "(Delivery happens in a background task — check "
                                "logs or the employee's inbox for confirmation.)"
                            )
                        s.update(label="Ticket updated", state="complete")
                        st.toast(
                            f"Ticket {selected_ticket_id} updated ✔",
                            icon="✅",
                        )
                        st.cache_data.clear()
                        st.rerun()
                    except APIError as e:
                        s.update(label="Update failed", state="error")
                        st.error(f"Failed to update ticket: {e.message}")


# =========================================================================
# TAB 2 — Employee Directory
# =========================================================================
with tab_directory:
    st.subheader("Company directory")
    try:
        employees = _fetch_employees(st.session_state["token"])
    except APIError as e:
        employees = []
        if e.status_code == 404:
            st.info(
                "The `/employees` endpoint is not available on this backend. "
                "Nothing to show here."
            )
        else:
            st.error(f"Couldn't load employees: {e.message}")

    if employees:
        edf = pd.DataFrame(employees)
        search = st.text_input("Search employees", placeholder="Name, email, department...")
        if search:
            s = search.strip().lower()
            mask = edf.astype(str).apply(lambda col: col.str.lower().str.contains(s, na=False))
            edf = edf[mask.any(axis=1)]
        st.caption(f"{len(edf)} employee(s)")
        st.dataframe(edf, use_container_width=True, hide_index=True)
    elif not employees:
        st.caption("No employee data available.")


# =========================================================================
# TAB 3 — Analytics
# =========================================================================
with tab_analytics:
    st.subheader("MAS performance analytics")

    if df_all.empty:
        st.write("Not enough data for analytics yet.")
    else:
        # Tickets by flow
        left, right = st.columns(2)
        with left:
            st.markdown("**Tickets by flow**")
            st.bar_chart(df_all["flow"].value_counts())
        with right:
            st.markdown("**Tickets by status**")
            st.bar_chart(df_all["status"].value_counts())

        # Avg resolution time per step (done/approved/closed only)
        st.markdown("**Avg resolution time per step** (hours)")
        resolved = df_all[
            df_all["status"].str.lower().isin(["done", "closed", "approved"])
            & df_all["created_at_dt"].notna()
            & df_all["updated_at_dt"].notna()
        ].copy()
        if resolved.empty:
            st.caption("No resolved tickets yet.")
        else:
            resolved["hours"] = (
                (resolved["updated_at_dt"] - resolved["created_at_dt"])
                .dt.total_seconds() / 3600.0
            )
            by_step = resolved.groupby("step")["hours"].mean().round(1).sort_values()
            if by_step.empty:
                st.caption("No data.")
            else:
                st.bar_chart(by_step)

        # Rejection-rate by step
        st.markdown("**Rejection rate by step**")
        by_step_total = df_all.groupby("step").size()
        by_step_rej = (
            df_all[df_all["status"].str.lower().isin(["rejected", "blocked"])]
            .groupby("step").size()
        )
        if by_step_total.empty:
            st.caption("No data.")
        else:
            rate = (
                (by_step_rej.reindex(by_step_total.index, fill_value=0) / by_step_total * 100)
                .round(1)
            )
            st.bar_chart(rate)

        # SLA risk: tickets with sla_due in the past and not completed
        st.markdown("**SLA risk**")
        now = pd.Timestamp.now()
        sla_df = df_all.copy()
        sla_df["sla_due_dt"] = pd.to_datetime(sla_df["sla_due"], errors="coerce")
        at_risk = sla_df[
            sla_df["sla_due_dt"].notna()
            & (sla_df["sla_due_dt"] < now)
            & ~sla_df["status"].str.lower().isin(["done", "closed", "approved"])
        ]
        if at_risk.empty:
            st.success("✅ No tickets past their SLA.")
        else:
            st.warning(f"⚠️ {len(at_risk)} ticket(s) past SLA due date.")
            st.dataframe(
                at_risk[[c for c in (
                    "ticket_id", "employee_name", "step", "status",
                    "sla_due", "assigned_to",
                ) if c in at_risk.columns]],
                use_container_width=True,
                hide_index=True,
            )
