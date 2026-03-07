
import streamlit as st, requests
API_URL = "http://localhost:8000"

def login_ui():
    st.title("Enterprise Onboarding & Offboarding")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login", type="primary"):
        with st.spinner("Authenticating..."):
            try:
                resp = requests.post(f"{API_URL}/auth/login", json={"email": email, "password": password})
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state['token'], st.session_state['profile'] = data['token'], data['profile']
                    st.rerun()
                else: st.error("Invalid credentials.")
            except Exception as e: st.error(f"Backend error: {e}")

def check_auth():
    if 'token' not in st.session_state: login_ui(); st.stop()
def logout(): st.session_state.clear(); st.rerun()