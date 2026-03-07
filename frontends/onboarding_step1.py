
import streamlit as st
import requests

API_URL = "http://localhost:8000"

def render():
    st.header("Step 1: Offer Letter")
    

    st.markdown("### Your Offer Details")
    st.info(f"Position: {st.session_state['profile'].get('role')}  \n"
            f"Department: {st.session_state['profile'].get('department')}")
    
    decision = st.radio("Do you accept this offer?", ("Yes, I accept", "No, I need to negotiate"))
    reason = ""
    
    if decision == "No, I need to negotiate":
        reason = st.text_area("Please explain your concerns (e.g., salary, start date):")
        
    if st.button("Submit Decision", type="primary"):
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        payload = {
            "accepted": decision == "Yes, I accept",
            "reason": reason
        }
        
        with st.spinner("Agents are processing your response..."):
            resp = requests.post(f"{API_URL}/onboarding/offer", json=payload, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("agent_decision")
                
                if status == "accepted":
                    st.success("Offer accepted! Proceeding to documents.")
                    st.session_state['step'] = 2
                    st.rerun()
                else:
                    st.warning(f"Your concerns have been logged: {data.get('logs')}. "
                               "An HR ticket has been opened. Please wait for HR to contact you.")
            else:
                st.error("Failed to submit decision. Please try again.")