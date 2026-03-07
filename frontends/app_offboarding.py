
import streamlit as st
import requests
from _auth import check_auth, logout

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Employee Offboarding", layout="wide")
check_auth()

headers = {"Authorization": f"Bearer {st.session_state['token']}"}
profile = st.session_state['profile']


if "active_step_off" not in st.session_state:
    st.session_state["active_step_off"] = None
if "chat_history_off" not in st.session_state:
    st.session_state["chat_history_off"] = [{"role": "assistant", "content": f"Hi {profile.get('name')}. I'm here to assist you with the offboarding process. What questions do you have?"}]


progress = {}
try:
    progress = requests.get(f"{API_URL}/progress/offboarding", headers=headers).json()
except Exception as e:
    st.error(f"Failed to connect to backend: {e}")
    st.stop()


st.sidebar.title(f"{profile.get('name')}")
st.sidebar.write(f"**Role:** {profile.get('role')} | **Dept:** {profile.get('department')}")
col_lo, col_ref = st.sidebar.columns(2)
with col_lo:
    if st.button("Logout", use_container_width=True): logout()
with col_ref:
    if st.button("🔄 Refresh", use_container_width=True):
        st.session_state["active_step_off"] = None
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💬 HR Support Chat")

chat_container = st.sidebar.container(height=450)
for msg in st.session_state["chat_history_off"]:
    chat_container.chat_message(msg["role"]).write(msg["content"])

if prompt := st.sidebar.chat_input("Ask a question about offboarding..."):
    st.session_state["chat_history_off"].append({"role": "user", "content": prompt})
    chat_container.chat_message("user").write(prompt)
    
    current_step = "General Offboarding"
    if progress.get('step1') in ["unlocked", "rejected"]: current_step = "Step 1: Initiation"
    elif progress.get('step2') in ["pending_hr", "unlocked", "rejected"]: current_step = "Step 2: HR Approval"
    elif progress.get('step3') in ["unlocked", "rejected"]: current_step = "Step 3: Exit Formalities"
    elif progress.get('step3') == "completed": current_step = "Offboarding Completed"

    with chat_container.chat_message("assistant"):
        with st.spinner("Typing..."):
            chat_payload = {
                "message": prompt,
                "flow": "offboarding",
                "current_step": current_step,
                "history": st.session_state["chat_history_off"][:-1]
            }
            try:
                resp = requests.post(f"{API_URL}/chat", json=chat_payload, headers=headers)
                if resp.status_code == 200:
                    reply = resp.json().get("reply", "Error generating response.")
                    st.write(reply)
                    st.session_state["chat_history_off"].append({"role": "assistant", "content": reply})
                else:
                    st.error("Chat service unavailable.")
            except Exception:
                st.error("Failed to connect to AI Support.")


st.title("Offboarding Portal")

def render_badge(status):
    badges = {"completed": "✅ **Completed**", "pending_hr": "⏳ **Pending HR Approval**", "unlocked": "🔓 **Action Required**", "rejected": "❌ **Action Required**"}
    return badges.get(status, "🔒 **Locked**")

col1, col2, col3 = st.columns(3)

with col1:
    with st.container(border=True):
        st.subheader("Step 1: Initiation")
        st.markdown(render_badge(progress.get('step1', 'locked')))
        if progress.get('step1') in ["unlocked", "rejected"]:
            if st.button("Start Offboarding", key="btn_off1", use_container_width=True):
                st.session_state["active_step_off"] = 1
                st.rerun()

with col2:
    with st.container(border=True):
        st.subheader("Step 2: HR Approval")
        st.markdown(render_badge(progress.get('step2', 'locked')))
        if progress.get('step2') in ["unlocked", "rejected"]:
            if st.button("Acknowledge", key="btn_off2", use_container_width=True):
                st.session_state["active_step_off"] = 2
                st.rerun()

with col3:
    with st.container(border=True):
        st.subheader("Step 3: Formalities")
        st.markdown(render_badge(progress.get('step3', 'locked')))
        if progress.get('step3') in ["unlocked", "rejected"]:
            if st.button("Finalize Exit", key="btn_off3", use_container_width=True):
                st.session_state["active_step_off"] = 3
                st.rerun()

st.divider()


if st.session_state["active_step_off"] is None and progress.get('step3') == "completed":
    st.success("Your offboarding process is complete. Please ensure all physical assets are returned to IT.")

elif st.session_state["active_step_off"] == 1:
    st.header("Step 1: Initiate Separation")
    st.warning("Submitting this form will officially notify your manager and the HR department.")
    reason = st.text_area("Reason for leaving", placeholder="e.g., Better opportunity, Relocation, Personal reasons...")
    early_release = st.checkbox("I am requesting an early release (waive notice period)")
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Resignation", type="primary"):
            if reason.strip():
                with st.spinner("Initiating offboarding sequence..."):
                    resp = requests.post(f"{API_URL}/offboarding/initiate", json={"reason": reason, "early_release": early_release}, headers=headers)
                    if resp.status_code == 200: st.session_state["active_step_off"] = None; st.rerun()
                    else: st.error(f"Error {resp.status_code}: {resp.text}")
            else: st.error("Please provide a reason for your departure.")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step_off"] = None; st.rerun()

elif st.session_state["active_step_off"] == 2:
    st.header("Step 2: Pending HR & Manager Approval")
    st.info("Your separation request requires manual approval from HR.")
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Acknowledge Wait", type="primary"):
            with st.spinner("Updating status..."):
                resp = requests.post(f"{API_URL}/offboarding/approval", headers=headers)
                if resp.status_code == 200: st.session_state["active_step_off"] = None; st.rerun()
                else: st.error(f"Error: {resp.text}")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step_off"] = None; st.rerun()

elif st.session_state["active_step_off"] == 3:
    st.header("Step 3: Exit Formalities")
    st.write("Please confirm your final working day to generate your clearance checklist.")
    last_day = st.date_input("Select your confirmed Last Working Day")
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Finalize Exit Plan", type="primary"):
            with st.spinner("Generating clearance tickets..."):
                resp = requests.post(f"{API_URL}/offboarding/exit", json={"last_day": last_day.strftime("%Y-%m-%d")}, headers=headers)
                if resp.status_code == 200: st.session_state["active_step_off"] = None; st.rerun()
                else: st.error(f"Error: {resp.text}")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step_off"] = None; st.rerun()