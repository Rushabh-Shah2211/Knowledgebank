import streamlit as st
import os
import time
import PyPDF2
import json
import pandas as pd
import plotly.express as px
from io import BytesIO
from docx import Document
from google import genai
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

st.set_page_config(page_title="Enterprise Legal Knowledge Bank", layout="wide", page_icon="🏛️")

# --- Authentication & Cloud Setup ---
# We load the secrets from Render Environment Variables
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SHEET_ID = os.environ.get("SPREADSHEET_ID")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")

# Sidebar for AI API Key
st.sidebar.header("⚙️ Settings")
api_key = st.sidebar.text_input("Enter Gemini API Key (for AI features):", type="password")
if api_key:
    st.sidebar.success("✅ API Key registered!")

@st.cache_resource
def get_google_clients():
    """Authenticates and returns Google Sheets and Drive clients."""
    if not GOOGLE_CREDS_JSON or not SHEET_ID or not DRIVE_FOLDER_ID:
        return None, None
    
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        
        # Sheets Client
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        # Drive Client
        drive_service = build('drive', 'v3', credentials=creds)
        
        return sh, drive_service
    except Exception as e:
        st.error(f"Google Auth Error: {e}")
        return None, None

sh, drive_service = get_google_clients()

def init_sheets():
    """Ensures headers exist in Google Sheets."""
    if sh:
        try:
            judgments_sheet = sh.worksheet("Judgments")
            if not judgments_sheet.row_values(1):
                judgments_sheet.append_row(["ID", "Case Name", "Act Name", "Section Number", "Authority", "Brief Facts", "Decision Held", "PDF File IDs", "AI Notes", "Status"])
                
            internal_sheet = sh.worksheet("Internal Usage")
            if not internal_sheet.row_values(1):
                internal_sheet.append_row(["ID", "Judgment ID", "Internal Matter Name", "Internal Notice", "Usage Notes", "AI Brief"])
        except Exception as e:
            st.error(f"Error initializing sheets: {e}")

if sh:
    init_sheets()

# --- Google Drive File Handlers ---
def upload_to_drive(file_buffer, file_name):
    """Uploads a file buffer to Google Drive and returns the File ID."""
    try:
        media = MediaIoBaseUpload(file_buffer, mimetype='application/pdf', resumable=True)
        file_metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"Drive Upload Error: {e}")
        return None

def download_from_drive(file_id):
    """Downloads a file from Google Drive into memory."""
    try:
        request = drive_service.files().get_media(fileId=file_id)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return fh.getvalue()
    except Exception as e:
        return None

# --- Helper Functions ---
def extract_text_from_buffers(pdf_buffers):
    text = ""
    for pdf_buffer in pdf_buffers:
        try:
            reader = PyPDF2.PdfReader(pdf_buffer)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        except Exception:
            pass
    return text

def ask_ai(prompt):
    if not api_key:
        return None, "Error: Please enter your Gemini API Key in the sidebar."
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text, None
    except Exception as e:
        return None, f"AI Error: {e}"

def create_word_docx(text, title="Legal Brief"):
    doc = Document()
    doc.add_heading(title, 0)
    doc.add_paragraph(text)
    bio = BytesIO()
    doc.save(bio)
    return bio.getvalue()

# --- Initialize Session State ---
if 'form_data' not in st.session_state:
    st.session_state.form_data = {
        "case_name": "", "act_name": "", "section_number": "", 
        "authority": "", "brief_facts": "", "decision_held": "", "ai_notes": ""
    }
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# --- UI Layout ---
if not sh:
    st.error("🚨 System not connected to Google Cloud. Please configure Environment Variables on Render.")
    st.stop()

st.title("🏛️ Enterprise Legal Knowledge Bank (Cloud)")

tab_dash, tab_search, tab_add, tab_link, tab_chat = st.tabs([
    "📊 Dashboard", "🔍 Search", "➕ Add Judgment", "🔗 Link & Draft", "💬 Chat with PDF"
])

# ==========================================
# TAB 1: DASHBOARD & ANALYTICS
# ==========================================
with tab_dash:
    st.header("Firm Knowledge Analytics")
    try:
        j_data = sh.worksheet("Judgments").get_all_records()
        i_data = sh.worksheet("Internal Usage").get_all_records()
        df_j = pd.DataFrame(j_data)
        
        col1, col2 = st.columns(2)
        col1.metric("Total Judgments Banked", len(j_data))
        col2.metric("Internal Matter Links", len(i_data))
        
        if not df_j.empty:
            st.markdown("---")
            c1, c2, c3 = st.columns(3)
            with c1:
                if 'Act Name' in df_j.columns and not df_j['Act Name'].replace('', pd.NA).dropna().empty:
                    fig1 = px.pie(df_j[df_j['Act Name'] != ''], names='Act Name', title='Judgments by Act', hole=0.4)
                    st.plotly_chart(fig1, use_container_width=True)
            with c2:
                if 'Authority' in df_j.columns and not df_j['Authority'].replace('', pd.NA).dropna().empty:
                    fig2 = px.histogram(df_j[df_j['Authority'] != ''], x='Authority', title='Judgments by Authority')
                    st.plotly_chart(fig2, use_container_width=True)
            with c3:
                if 'Status' in df_j.columns:
                    fig3 = px.pie(df_j, names='Status', title='Law Status Distribution')
                    st.plotly_chart(fig3, use_container_width=True)
    except Exception as e:
        st.info("Add your first judgment to populate the dashboard.")

# ==========================================
# TAB 2: SEARCH & FILTER
# ==========================================
with tab_search:
    st.header("Search and Filter Judgments")
    search_term = st.text_input("Universal Search (Case Name, Facts, Decision):").lower()
    
    try:
        judgments = sh.worksheet("Judgments").get_all_records()
        internal_uses = sh.worksheet("Internal Usage").get_all_records()
        
        results = []
        if search_term:
            for row in judgments:
                if (search_term in str(row.get('Case Name', '')).lower() or 
                    search_term in str(row.get('Brief Facts', '')).lower() or 
                    search_term in str(row.get('Decision Held', '')).lower()):
                    results.append(row)
        else:
            results = judgments # Show all if no search
            
        if results:
            st.success(f"Showing {len(results)} judgment(s).")
            for row in results:
                j_id = row.get("ID")
                c_name = row.get("Case Name")
                status = row.get("Status", "🟢 Good Law")
                
                with st.expander(f"{status} | {c_name} | {row.get('Act Name')} - Sec {row.get('Section Number')}"):
                    if "🛑" in status:
                        st.error("WARNING: This judgment has been marked as Overruled or Bad Law.")
                    
                    st.markdown(f"**Authority:** {row.get('Authority')}")
                    st.markdown(f"**Brief Facts:**\n{row.get('Brief Facts')}")
                    st.markdown(f"**Decision Held:**\n{row.get('Decision Held')}")
                    
                    # Match Internal Usage
                    linked_uses = [u for u in internal_uses if str(u.get('Judgment ID')) == str(j_id)]
                    if linked_uses:
                        st.markdown("---")
                        st.markdown("**📌 Internal Usage:**")
                        for use in linked_uses:
                            st.markdown(f"- Used in: **{use.get('Internal Matter Name')}**")
                            if use.get('AI Brief'):
                                docx_file = create_word_docx(use['AI Brief'], f"Brief - {c_name}")
                                st.download_button("📄 Export Brief to Word", data=docx_file, file_name=f"Brief_{c_name}.docx", key=f"w_{j_id}_{use['ID']}")
                    
                    # PDF Downloads from Drive
                    file_ids = str(row.get("PDF File IDs", "")).split(",")
                    if file_ids and file_ids[0] != "":
                        st.markdown("**Attachments:**")
                        for idx, fid in enumerate(file_ids):
                            if fid.strip():
                                file_bytes = download_from_drive(fid.strip())
                                if file_bytes:
                                    st.download_button(label=f"⬇️ Download PDF {idx+1}", data=file_bytes, file_name=f"Judgment_{j_id}_{idx+1}.pdf", mime="application/pdf", key=f"dl_{fid}")
                                else:
                                    st.warning("Failed to load PDF from Drive.")
    except Exception as e:
        st.warning("Could not fetch records.")

# ==========================================
# TAB 3: ADD NEW JUDGMENT
# ==========================================
with tab_add:
    st.header("1. Upload & AI Auto-Fill")
    uploaded_files = st.file_uploader("Upload Judgments (PDF)", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🤖 AI: Read PDFs & Auto-Fill"):
        if uploaded_files and api_key:
            with st.spinner("Extracting details..."):
                pdf_text = extract_text_from_buffers(uploaded_files)
                prompt = f"""Extract details from this judgment into JSON format ONLY with keys: "case_name", "act_name", "section_number", "authority", "brief_facts", "decision_held", "ai_notes". Text: {pdf_text[:30000]}"""
                res, err = ask_ai(prompt)
                if not err:
                    try:
                        data = json.loads(res.replace("```json", "").replace("```", "").strip())
                        for key in st.session_state.form_data.keys():
                            st.session_state.form_data[key] = data.get(key, "")
                        st.success("Auto-filled below!")
                    except:
                        st.error("AI output formatting failed. Fill manually.")
        else:
            st.warning("Upload files and enter API key.")

    st.header("2. Review & Save to Cloud")
    with st.form("add_judgment_form", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            case_name = st.text_input("Name of Case *", value=st.session_state.form_data["case_name"])
            act_name = st.text_input("Act Name", value=st.session_state.form_data["act_name"])
        with c2:
            section_num = st.text_input("Section Number", value=st.session_state.form_data["section_number"])
            authority = st.text_input("Authority", value=st.session_state.form_data["authority"])
        with c3:
            status = st.selectbox("Current Status", ["🟢 Good Law", "🟡 Distinguished / Caution", "🛑 Overruled / Bad Law"])
            
        brief_facts = st.text_area("Brief Facts *", value=st.session_state.form_data["brief_facts"])
        decision_held = st.text_area("Decision Held *", value=st.session_state.form_data["decision_held"])
        ai_notes = st.text_area("AI Notes", value=st.session_state.form_data["ai_notes"])
        
        if st.form_submit_button("✅ Upload & Save to Google Sheets"):
            if case_name and brief_facts and decision_held:
                with st.spinner("Uploading to Google Drive and saving to Sheets..."):
                    j_id = str(int(time.time()))
                    drive_file_ids = []
                    
                    if uploaded_files:
                        for f in uploaded_files:
                            file_buffer = BytesIO(f.getbuffer())
                            fid = upload_to_drive(file_buffer, f"{j_id}_{f.name}")
                            if fid: drive_file_ids.append(fid)
                    
                    row_data = [j_id, case_name, act_name, section_num, authority, brief_facts, decision_held, ",".join(drive_file_ids), ai_notes, status]
                    sh.worksheet("Judgments").append_row(row_data)
                    
                    st.session_state.form_data = {k: "" for k in st.session_state.form_data}
                    st.success("Saved successfully to the Cloud!")

# ==========================================
# TAB 4: LINK TO INTERNAL CASE
# ==========================================
with tab_link:
    st.header("Mark Judgment & Draft AI Brief")
    try:
        judgments = sh.worksheet("Judgments").get_all_records()
        if judgments:
            j_dict = {f"{r['Status']} {r['Case Name']}": r for r in judgments}
            selected_j = st.selectbox("Select Precedent", options=list(j_dict.keys()))
            j_data = j_dict[selected_j]
            
            if "🛑" in j_data['Status']:
                st.error("⚠️ WARNING: You are attempting to rely on a case marked as OVERRULED/BAD LAW.")
                
            internal_case_name = st.text_input("Internal Matter / Client Name *")
            notice = st.text_area("Legal Notice (Text)", height=150)
            notes = st.text_area("Your Strategy/Notes", height=100)
            draft_ai = st.checkbox("🤖 Use AI to draft brief")
            
            if st.button("Process & Save Link"):
                if internal_case_name:
                    ai_brief_text = ""
                    if draft_ai and notice:
                        with st.spinner("Drafting brief..."):
                            prompt = f"Matter: '{internal_case_name}'. Notice: '{notice}'. Strategy: {notes}. Precedent Facts: {j_data['Brief Facts']}. Precedent Decision: {j_data['Decision Held']}. Draft a professional 3 paragraph legal brief applying precedent to notice."
                            ai_brief_text, err = ask_ai(prompt)
                    
                    usage_id = str(int(time.time()))
                    row_data = [usage_id, str(j_data['ID']), internal_case_name, notice, notes, ai_brief_text]
                    sh.worksheet("Internal Usage").append_row(row_data)
                    
                    st.success("Linked in Google Sheets!")
                    if ai_brief_text:
                        st.info(ai_brief_text)
                        docx_file = create_word_docx(ai_brief_text, f"Brief - {internal_case_name}")
                        st.download_button("📄 Download Brief as Word", data=docx_file, file_name=f"Brief_{internal_case_name}.docx")
        else:
            st.info("No judgments found in Google Sheets.")
    except Exception as e:
        st.error("Error connecting to Google Sheets.")

# ==========================================
# TAB 5: CHAT WITH PDF
# ==========================================
with tab_chat:
    st.header("💬 Interactive Q&A with Judgments")
    try:
        chat_judgments = [row for row in sh.worksheet("Judgments").get_all_records() if row.get("PDF File IDs")]
        if chat_judgments:
            c_dict = {r['Case Name']: r for r in chat_judgments}
            selected_chat_j = st.selectbox("Select a Judgment to Chat with:", options=list(c_dict.keys()))
            
            user_question = st.text_input("Ask a question about this specific judgment:")
            if st.button("Ask AI"):
                if user_question and api_key:
                    with st.spinner("Fetching PDF from Google Drive and analyzing..."):
                        file_ids = str(c_dict[selected_chat_j]["PDF File IDs"]).split(",")
                        doc_text = ""
                        for fid in file_ids:
                            if fid.strip():
                                pdf_bytes = download_from_drive(fid.strip())
                                if pdf_bytes:
                                    reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
                                    for page in reader.pages:
                                        doc_text += page.extract_text() + "\n"
                        
                        if doc_text:
                            prompt = f"Based ONLY on the following legal judgment text, answer this question: {user_question}\n\nJudgment Text:\n{doc_text[:35000]}"
                            answer, err = ask_ai(prompt)
                            if err:
                                st.error(err)
                            else:
                                st.session_state.chat_history.append({"q": user_question, "a": answer})
                        else:
                            st.error("Could not extract text from the Drive files.")
                elif not api_key:
                    st.warning("API Key required.")
                    
            # Display Chat History
            for chat in reversed(st.session_state.chat_history):
                st.markdown(f"**🧑‍⚖️ You:** {chat['q']}")
                st.info(f"**🤖 AI:** {chat['a']}")
                st.markdown("---")
        else:
            st.info("No judgments with uploaded PDFs found.")
    except Exception as e:
        st.warning("Error fetching data.")