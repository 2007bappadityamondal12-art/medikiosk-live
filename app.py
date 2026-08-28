import streamlit as st
from pymongo import MongoClient
import hashlib
from datetime import datetime
import random # Added to generate unique IDs

# ---------------------------------------------------------
# 1. DATABASE CONFIGURATION
# ---------------------------------------------------------
# Pulls the secret from Streamlit Cloud directly
MONGO_URI = st.secrets["MONGO_URI"]
MASTER_DOCTOR_KEY = "DOC-SECURE-2026"

@st.cache_resource
def get_database():
    client = MongoClient(MONGO_URI)
    return client["medikiosk_db"]

db = get_database()
users_col = db["users"]
intakes_col = db["intakes"]

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password, role):
    if users_col.find_one({"username": username}):
        return False
    
    # Generate a unique 6-digit ID for patients, and a 4-digit ID for doctors
    unique_id = f"PT-{random.randint(100000, 999999)}" if role == "Patient" else f"DR-{random.randint(1000, 9999)}"
    
    users_col.insert_one({
        "username": username,
        "password_hash": hash_password(password),
        "role": role,
        "unique_id": unique_id, # Saves the ID to the database
        "created_at": datetime.utcnow()
    })
    return True

def authenticate_user(username, password, expected_role):
    user = users_col.find_one({
        "username": username,
        "password_hash": hash_password(password),
        "role": expected_role
    })
    # Return both the role and the unique ID if login is successful
    if user:
        # get() is used in case older accounts don't have an ID yet
        return {"role": user["role"], "unique_id": user.get("unique_id", "N/A")}
    return None

# ---------------------------------------------------------
# 2. SESSION STATE MANAGEMENT
# ---------------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.unique_id = "" # Added unique ID to session memory
    st.session_state.active_portal = None

def logout():
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.role = ""
    st.session_state.unique_id = ""
    st.session_state.active_portal = None
    st.rerun()

st.set_page_config(page_title="MediKiosk Cloud Portal", page_icon="🏥", layout="wide")

# ---------------------------------------------------------
# 3. PORTAL SELECTION & AUTHENTICATION
# ---------------------------------------------------------
if not st.session_state.logged_in:
    if st.session_state.active_portal is None:
        st.title("🏥 MediKiosk Cloud System")
        st.write("Please select your portal to continue:")
        
        col1, col2 = st.columns(2)
        with col1:
            st.info("**Citizen / Patient Portal**\n\nSubmit intake notes and view records.")
            if st.button("Enter Citizen Portal", use_container_width=True):
                st.session_state.active_portal = "Patient"
                st.rerun()
                
        with col2:
            st.error("**Doctor / Authority Portal**\n\nReview real-time live OPD queues.")
            if st.button("Enter Doctor Portal", use_container_width=True):
                st.session_state.active_portal = "Doctor"
                st.rerun()
    else:
        portal = st.session_state.active_portal
        st.button("← Back to Selection", on_click=lambda: st.session_state.update(active_portal=None))
        st.title(f"{'🩺' if portal == 'Doctor' else '📋'} {portal} Portal")
        
        tab_login, tab_register = st.tabs(["🔑 Login", "📝 Sign Up"])

        with tab_login:
            login_user = st.text_input("Username", key="login_u")
            login_pass = st.text_input("Password", type="password", key="login_p")
            
            if st.button(f"Log In to {portal} Portal", type="primary"):
                user_data = authenticate_user(login_user, login_pass, portal)
                if user_data:
                    st.session_state.logged_in = True
                    st.session_state.username = login_user
                    st.session_state.role = user_data["role"]
                    st.session_state.unique_id = user_data["unique_id"]
                    st.rerun()
                else:
                    st.error(f"Invalid credentials or incorrect portal access.")

        with tab_register:
            reg_user = st.text_input("Choose Username", key="reg_u")
            reg_pass = st.text_input("Choose Password", type="password", key="reg_p")
            
            doctor_key = ""
            if portal == "Doctor":
                doctor_key = st.text_input("Doctor Authorization Key", type="password")
                
            if st.button(f"Register as {portal}"):
                if not reg_user or not reg_pass:
                    st.warning("Please fill in all required fields.")
                elif portal == "Doctor" and doctor_key != MASTER_DOCTOR_KEY:
                    st.error("❌ Invalid Doctor Authorization Key!")
                else:
                    if register_user(reg_user, reg_pass, portal):
                        st.success("Account created successfully! Please log in.")
                    else:
                        st.error("Username already exists.")

# ---------------------------------------------------------
# 4. LOGGED-IN DASHBOARDS (CONNECTED TO MONGODB)
# ---------------------------------------------------------
else:
    top_col1, top_col2 = st.columns([8, 2])
    with top_col1:
        # Now displays the unique ID at the top of the screen
        st.caption(f"Logged in as **{st.session_state.username}** | ID: **{st.session_state.unique_id}** ({st.session_state.role})")
    with top_col2:
        if st.button("Log Out"):
            logout()
    st.markdown("---")

    # --- DOCTOR VIEW ---
    if st.session_state.role == "Doctor":
        st.title("🩺 Live Physician OPD Dashboard")
        st.subheader("Incoming Patient Intake Queue")
        
        records = list(intakes_col.find({}, {"_id": 0}).sort("timestamp", -1))
        if records:
            st.dataframe(records, use_container_width=True)
        else:
            st.info("No patient intake submissions currently in the queue.")

    # --- PATIENT VIEW ---
    elif st.session_state.role == "Patient":
        st.title("📋 Citizen Health Intake")
        st.write(f"Welcome back. Your Patient ID is **{st.session_state.unique_id}**.")
        
        tab_intake, tab_history = st.tabs(["📝 New Intake", "📂 My Past Records"])
        
        # New Form Submission
        with tab_intake:
            st.subheader("Submit New Symptoms")
            symptoms = st.text_area("Describe your primary symptoms:")
            duration = st.text_input("Duration of symptoms (e.g., 3 days, 2 weeks):")
            
            if st.button("Submit to Doctor Queue", type="primary"):
                if symptoms:
                    intakes_col.insert_one({
                        "patient_id": st.session_state.unique_id, # Saves the ID with the intake
                        "patient_username": st.session_state.username,
                        "symptoms": symptoms,
                        "duration": duration,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "Awaiting Review"
                    })
                    st.success("Your intake details have been sent to the doctor dashboard!")
                else:
                    st.warning("Please enter your symptoms before submitting.")
        
        # History View
        with tab_history:
            st.subheader("Your Submission History")
            # Searches the database ONLY for records matching this specific user
            my_records = list(intakes_col.find({"patient_username": st.session_state.username}, {"_id": 0}).sort("timestamp", -1))
            
            if my_records:
                st.dataframe(my_records, use_container_width=True)
            else:
                st.info("You have not submitted any intake forms yet.")
