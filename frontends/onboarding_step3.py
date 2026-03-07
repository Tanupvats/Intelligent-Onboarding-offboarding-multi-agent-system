
import streamlit as st
import requests

API_URL = "http://localhost:8000"

def render():
    st.header("Step 3: IT Assets & Provisioning")
    st.write("Select the hardware required for your role.")
    
    laptop_type = st.selectbox("Select Laptop", ["MacBook Pro 14", "MacBook Air", "Windows ThinkPad", "Linux Dell XPS"])
    accessories = st.multiselect("Select Accessories", ["External Monitor", "Wireless Mouse", "Mechanical Keyboard", "Headset"])
    
    if st.button("Submit Request", type="primary"):
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        payload = {
            "laptop_type": laptop_type,
            "accessories": accessories
        }
        
        with st.spinner("IT Agent is reviewing your request against department policies..."):
            resp = requests.post(f"{API_URL}/onboarding/assets", json=payload, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("agent_decision")
                
                if status == "approved":
                    st.success("Hardware request approved and sent to IT!")
                    st.session_state['step'] = 4 
                    st.rerun()
                else:
                    agent_reason = data.get('logs', ['Policy violation.'])[-1]
                    st.warning(f"**Request Blocked:** {agent_reason}")
                    st.info("A ticket has been opened for IT to review your request manually.")
            else:
                st.error("Submission failed.")