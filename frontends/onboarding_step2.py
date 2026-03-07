
import streamlit as st
import requests

API_URL = "http://localhost:8000"

def render():
    st.header("Step 2: Document Verification")
    st.write("Please upload a valid government-issued ID.")
    
    uploaded_files = st.file_uploader("Upload ID", accept_multiple_files=True)
    
    if st.button("Submit Documents", type="primary"):
        if not uploaded_files:
            st.error("Please upload at least one file.")
            return
            
        headers = {"Authorization": f"Bearer {st.session_state['token']}"}
        files_to_send = [("files", (f.name, f.getvalue(), f.type)) for f in uploaded_files]
        
        with st.spinner("AI Compliance Agent is verifying your documents..."):
            resp = requests.post(f"{API_URL}/onboarding/documents", files=files_to_send, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("agent_decision")
                
                if status == "approved":
                    st.success("Documents verified and approved!")
                    st.session_state['step'] = 3
                    st.rerun()
                else:
                    
                    agent_reason = data.get('logs', ['No reason provided.'])[-1]
                    st.error(f"**Verification Failed:** {agent_reason}")
                    st.info("Please upload a clearer document and try again.")
            else:
                st.error("Upload failed due to a server error.")