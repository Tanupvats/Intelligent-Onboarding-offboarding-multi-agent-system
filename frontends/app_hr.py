
import streamlit as st
import requests
import pandas as pd
import os
from _auth import check_auth, logout

API_URL = "http://localhost:8000"

st.set_page_config(page_title="HR Ops Dashboard", layout="wide")


check_auth()
profile = st.session_state['profile']

if profile.get('role') not in ['hr', 'admin']:
    st.error("Access Denied. You do not have HR/Admin privileges.")
    if st.button("Logout"):
        logout()
    st.stop()


st.sidebar.title("HR Control Center")
st.sidebar.write(f"**Operator:** {profile.get('name')}")
if st.sidebar.button("Logout"):
    logout()
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()


@st.cache_data(ttl=10)
def fetch_tickets(token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(f"{API_URL}/tickets", headers=headers)
        if resp.status_code == 200:
            return resp.json().get('tickets', [])
    except Exception as e:
        st.error(f"Failed to fetch tickets: {e}")
    return []

@st.cache_data(ttl=60)
def fetch_employees(token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(f"{API_URL}/employees", headers=headers)
        if resp.status_code == 200:
            return resp.json().get('employees', [])
    except Exception as e:
        st.error(f"Failed to fetch employees: {e}")
    return []


tab1, tab2, tab3 = st.tabs(["🎫 Ticket Queue", "👥 Employee Directory", "📊 System Analytics"])

tickets = fetch_tickets(st.session_state['token'])

with tab1:
    st.header("Active Workflows & Agent Exceptions")
    
    if not tickets:
        st.info("No tickets found. The MAS queue is empty.")
    else:
        df = pd.DataFrame(tickets)
        
       
        status_filter = st.multiselect("Filter by Status", df['status'].unique(), default=[s for s in df['status'].unique() if s.lower() in ['open', 'pending', 'blocked', 'rejected']])
        filtered_df = df[df['status'].isin(status_filter)]
        
        st.dataframe(
            filtered_df[['ticket_id', 'flow', 'step', 'employee_name', 'status', 'priority', 'assigned_to', 'description']],
            use_container_width=True,
            hide_index=True
        )
        
        st.divider()
        st.subheader("Verify Documents & Update Ticket")
        
        selected_ticket_id = st.selectbox("Select Ticket ID to Update", filtered_df['ticket_id'].tolist() if not filtered_df.empty else [])
        
        if selected_ticket_id:
            t_detail = next((t for t in tickets if t['ticket_id'] == selected_ticket_id), {})
            
            
            attachments = t_detail.get('attachments', '')
            if attachments:
                st.markdown("### 📎 Attached Documents")
                st.write("Review the candidate's uploaded files before approving.")
                
                
                file_paths = [p for p in attachments.split(';') if p.strip()]
                
                
                cols = st.columns(min(len(file_paths), 4)) 
                for idx, path in enumerate(file_paths):
                    file_name = os.path.basename(path)
                    
                    
                    file_url = f"{API_URL}/files/get"
                    try:
                        res = requests.get(file_url, params={"path": path}, headers={"Authorization": f"Bearer {st.session_state['token']}"})
                        if res.status_code == 200:
                            with cols[idx % 4]:
                                st.download_button(
                                    label=f"⬇️ Download {file_name}",
                                    data=res.content,
                                    file_name=file_name,
                                    mime=res.headers.get('Content-Type', 'application/octet-stream')
                                )
                        else:
                            st.error(f"Could not load {file_name} (Error {res.status_code})")
                    except Exception as e:
                        st.error(f"Error fetching {file_name}: {e}")
            
            with st.form("update_ticket_form"):
                col1, col2 = st.columns(2)
                with col1:
                    
                    status_options = ['Open', 'Pending', 'Approved', 'Rejected', 'Done', 'Closed']
                    current_status = t_detail.get('status', 'Open').capitalize()
                    default_idx = status_options.index(current_status) if current_status in status_options else 0
                    
                    new_status = st.selectbox("Status", status_options, index=default_idx)
                    new_assignee = st.text_input("Assign To", value=t_detail.get('assigned_to', ''))
                with col2:
                    comments = st.text_area("HR Comments / Override Reason", value=t_detail.get('comments', ''))
                    notify_email = st.text_input("Notify Employee Email (Optional)", placeholder="Leave blank to use default")
                
                submitted = st.form_submit_button("Update Ticket & Notify Employee", type="primary")
                
                if submitted:
                    update_payload = {
                        "ticket_id": selected_ticket_id,
                        "status": new_status,
                        "assigned_to": new_assignee,
                        "comments": comments,
                        "email": notify_email
                    }
                    headers = {"Authorization": f"Bearer {st.session_state['token']}"}
                    
                    with st.spinner("Pushing update to MAS and sending email..."):
                        update_resp = requests.post(f"{API_URL}/tickets/update", json=update_payload, headers=headers)
                        
                        if update_resp.status_code == 200:
                            st.success(f"Ticket {selected_ticket_id} updated successfully!")
                            st.cache_data.clear() # Clear cache to refresh the table
                            st.rerun()
                        else:
                            st.error("Failed to update ticket.")

with tab2:
    st.header("Company Directory")
    employees = fetch_employees(st.session_state['token'])
    if employees:
        st.dataframe(pd.DataFrame(employees), use_container_width=True, hide_index=True)
    else:
        st.info("No employee data found.")

with tab3:
    st.header("MAS Performance Analytics")
    if tickets:
        col1, col2, col3 = st.columns(3)
        df_stats = pd.DataFrame(tickets)
        col1.metric("Total Tickets", len(df_stats))
        col2.metric("Open Exceptions", len(df_stats[df_stats['status'].str.lower().isin(['open', 'pending'])]))
        col3.metric("Completed Workflows", len(df_stats[df_stats['status'].str.lower().isin(['done', 'closed', 'approved'])]))
        
        st.bar_chart(df_stats['flow'].value_counts())
    else:
        st.write("Not enough data for analytics.")