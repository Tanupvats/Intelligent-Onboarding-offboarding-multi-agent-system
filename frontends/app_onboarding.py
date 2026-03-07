
import streamlit as st
import requests
from _auth import check_auth, logout

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Candidate Onboarding", layout="wide")
check_auth()

headers = {"Authorization": f"Bearer {st.session_state['token']}"}
profile = st.session_state['profile']


if "active_step" not in st.session_state:
    st.session_state["active_step"] = None
if "chat_history_onb" not in st.session_state:
    st.session_state["chat_history_onb"] = [{"role": "assistant", "content": f"Hi {profile.get('name')}! I'm your AI HR Guide. How can I help with your onboarding today?"}]


progress = {}
try:
    progress = requests.get(f"{API_URL}/progress/onboarding", headers=headers).json()
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
        st.session_state["active_step"] = None
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("💬 HR Support Chat")


chat_container = st.sidebar.container(height=450)
for msg in st.session_state["chat_history_onb"]:
    chat_container.chat_message(msg["role"]).write(msg["content"])


if prompt := st.sidebar.chat_input("Ask a question about onboarding..."):
    st.session_state["chat_history_onb"].append({"role": "user", "content": prompt})
    chat_container.chat_message("user").write(prompt)
    
    
    current_step = "General Onboarding"
    if progress.get('step1') in ["unlocked", "rejected"]: current_step = "Step 1: Offer Letter"
    elif progress.get('step2') in ["unlocked", "rejected"]: current_step = "Step 2: Document Verification"
    elif progress.get('step3') in ["unlocked", "rejected"]: current_step = "Step 3: IT Hardware Provisioning"
    elif progress.get('step3') == "completed": current_step = "Onboarding Completed"

    with chat_container.chat_message("assistant"):
        with st.spinner("Typing..."):
            chat_payload = {
                "message": prompt,
                "flow": "onboarding",
                "current_step": current_step,
                "history": st.session_state["chat_history_onb"][:-1] 
            }
            try:
                resp = requests.post(f"{API_URL}/chat", json=chat_payload, headers=headers)
                if resp.status_code == 200:
                    reply = resp.json().get("reply", "Error generating response.")
                    st.write(reply)
                    st.session_state["chat_history_onb"].append({"role": "assistant", "content": reply})
                else:
                    st.error("Chat service unavailable.")
            except Exception:
                st.error("Failed to connect to AI Support.")


st.title("Onboarding Portal")

def render_badge(status):
    badges = {"completed": "✅ **Completed**", "pending_hr": "⏳ **Pending HR Approval**", "unlocked": "🔓 **Action Required**", "rejected": "❌ **Action Required**"}
    return badges.get(status, "🔒 **Locked**")

col1, col2, col3 = st.columns(3)

with col1:
    with st.container(border=True):
        st.subheader("Step 1: Offer Letter")
        st.markdown(render_badge(progress.get('step1', 'locked')))
        if progress.get('step1') in ["unlocked", "rejected"]:
            if st.button("Review Offer", key="btn_step1", use_container_width=True):
                st.session_state["active_step"] = 1
                st.rerun()

with col2:
    with st.container(border=True):
        st.subheader("Step 2: Verification")
        st.markdown(render_badge(progress.get('step2', 'locked')))
        if progress.get('step2') in ["unlocked", "rejected"]:
            if st.button("Upload Documents", key="btn_step2", use_container_width=True):
                st.session_state["active_step"] = 2
                st.rerun()

with col3:
    with st.container(border=True):
        st.subheader("Step 3: IT Assets")
        st.markdown(render_badge(progress.get('step3', 'locked')))
        if progress.get('step3') in ["unlocked", "rejected"]:
            if st.button("Select Hardware", key="btn_step3", use_container_width=True):
                st.session_state["active_step"] = 3
                st.rerun()

st.divider()


if st.session_state["active_step"] is None and progress.get('step3') == "completed":
    st.success("🎉 You have completed all onboarding steps! HR will contact you shortly with your start date.")
    st.balloons()

elif st.session_state["active_step"] == 1:
    st.header("Step 1: Offer Letter Review")
    st.info(f"**Position:** {profile.get('role')} | **Department:** {profile.get('department')}")
    dec = st.radio("Do you accept this offer?", ("Yes, I accept", "No, I need to negotiate"))
    reason = st.text_area("Please detail your concerns (Optional if accepting):") if dec == "No, I need to negotiate" else ""
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Decision", type="primary"):
            with st.spinner("Processing..."):
                resp = requests.post(f"{API_URL}/onboarding/offer", json={"accepted": dec == "Yes, I accept", "reason": reason}, headers=headers)
                if resp.status_code == 200:
                    st.session_state["active_step"] = None; st.rerun()
                else: st.error(f"Error {resp.status_code}: {resp.text}")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step"] = None; st.rerun()

elif st.session_state["active_step"] == 2:
    st.header("Step 2: Document Verification")
    if progress.get('step2') == "rejected":
        st.error(f"**Previous Upload Rejected:** {progress.get('tickets', {}).get('step2', {}).get('description', 'Documents did not meet compliance standards.')}")
    docs = st.file_uploader("Upload Government ID (PDF, JPG, PNG)", accept_multiple_files=True)
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Submit Documents", type="primary"):
            if docs:
                with st.spinner("Securely uploading..."):
                    files_payload = [("files", (f.name, f.getvalue(), f.type)) for f in docs]
                    resp = requests.post(f"{API_URL}/onboarding/documents", files=files_payload, headers=headers)
                    if resp.status_code == 200: st.session_state["active_step"] = None; st.rerun()
                    else: st.error(f"Server Error {resp.status_code}: {resp.text}")
            else: st.warning("⚠️ Please attach a file.")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step"] = None; st.rerun()

elif st.session_state["active_step"] == 3:
    st.header("Step 3: IT Hardware Provisioning")
    lap = st.selectbox("Select Primary Device", ["MacBook Pro 14-inch", "MacBook Air M3", "Windows ThinkPad T14", "Dell XPS 15"])
    acc = st.multiselect("Select Peripherals", ["External 27-inch Monitor", "Wireless Mouse", "Mechanical Keyboard", "Noise-Cancelling Headset"])
    col_sub, col_cancel = st.columns([1, 5])
    with col_sub:
        if st.button("Request Assets", type="primary"):
            with st.spinner("Running IT Policy Check..."):
                resp = requests.post(f"{API_URL}/onboarding/assets", json={"laptop_type": lap, "accessories": acc}, headers=headers)
                if resp.status_code == 200: st.session_state["active_step"] = None; st.rerun()
                else: st.error(f"Error {resp.status_code}: {resp.text}")
    with col_cancel:
        if st.button("Cancel"): st.session_state["active_step"] = None; st.rerun()