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
from google.cloud import storage

st.set_page_config(page_title="RBS Legal Knowledge Bank", layout="wide", page_icon="🏛️")

# --- Authentication & Cloud Setup ---
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SHEET_ID = os.environ.get("SPREADSHEET_ID")
GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME")
api_key = os.environ.get("GEMINI_API_KEY")

@st.cache_resource
def get_google_clients():
    if not GOOGLE_CREDS_JSON or not SHEET_ID or not GCS_BUCKET_NAME:
        return None, None
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        sheet_creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(sheet_creds)
        sh = gc.open_by_key(SHEET_ID)
        storage_client = storage.Client.from_service_account_info(creds_dict)
        return sh, storage_client
    except Exception as e:
        st.error(f"Google Auth Error: {e}")
        return None, None

sh, storage_client = get_google_clients()

def init_sheets():
    if sh:
        try:
            worksheet_titles = [ws.title for ws in sh.worksheets()]
            
            if "Judgments" not in worksheet_titles:
                sh.add_worksheet(title="Judgments", rows="1000", cols="10")
            judgments_sheet = sh.worksheet("Judgments")
            if not judgments_sheet.row_values(1):
                judgments_sheet.append_row(["ID", "Case Name", "Act Name", "Section Number", "Authority", "Brief Facts", "Decision Held", "PDF File IDs", "AI Notes", "Status"])
                
            if "Internal Usage" not in worksheet_titles:
                sh.add_worksheet(title="Internal Usage", rows="1000", cols="10")
            internal_sheet = sh.worksheet("Internal Usage")
            if not internal_sheet.row_values(1):
                internal_sheet.append_row(["ID", "Judgment ID", "Internal Matter Name", "Internal Notice", "Usage Notes", "AI Brief"])
                
            # NEW: Notice Replies Sheet
            if "Notice Replies" not in worksheet_titles:
                sh.add_worksheet(title="Notice Replies", rows="1000", cols="10")
            notice_sheet = sh.worksheet("Notice Replies")
            if not notice_sheet.row_values(1):
                notice_sheet.append_row(["ID", "Matter Name", "Notice Text", "Internal Judgments Used", "External References", "Final Reply"])
                
        except Exception as e:
            st.error(f"Error initializing sheets: {e}")

if sh:
    init_sheets()

# --- Google Cloud Storage File Handlers ---
def upload_to_gcs(file_buffer, file_name):
    try:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(file_name)
        file_buffer.seek(0)
        blob.upload_from_file(file_buffer, content_type='application/pdf')
        return file_name
    except Exception as e:
        st.error(f"GCS Upload Error: {e}")
        return None

def download_from_gcs(file_name):
    try:
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(file_name)
        return blob.download_as_bytes()
    except Exception as e:
        return None

# --- Helper Functions ---
def extract_text_from_buffers(pdf_buffers):
    text = ""
    for pdf_buffer in pdf_buffers:
        try:
            pdf_buffer.seek(0)
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
        return None, "Error: API Key is missing from Environment Variables."
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        return response.text, None
    except Exception as e:
        return None, f"AI Error: {e}"

def create_word_docx(text, title="Legal Document"):
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
    
# NEW: Session State for Notice Reply Workflow
if 'notice_text' not in st.session_state:
    st.session_state.notice_text = ""
if 'suggested_cases' not in st.session_state:
    st.session_state.suggested_cases = []
if 'drafted_reply' not in st.session_state:
    st.session_state.drafted_reply = ""

# --- UI Layout ---
if not sh or not storage_client:
    st.error("🚨 System not connected to Google Cloud. Please configure Environment Variables on Render.")
    st.stop()

st.title("RBS Knowledge Bank ")

tab_dash, tab_search, tab_add, tab_link, tab_reply, tab_chat = st.tabs([
    "📊 Dashboard", "🔍 Search", "➕ Add Judgment", "🔗 Link to Case", "📝 Draft Notice Reply", "💬 Chat with PDF"
])

# ==========================================
# TAB 1: DASHBOARD
# ==========================================
with tab_dash:
    st.header("Firm Knowledge Analytics")
    try:
        j_data = sh.worksheet("Judgments").get_all_records()
        i_data = sh.worksheet("Internal Usage").get_all_records()
        r_data = sh.worksheet("Notice Replies").get_all_records()
        df_j = pd.DataFrame(j_data)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Judgments Banked", len(j_data))
        col2.metric("Quick Links", len(i_data))
        col3.metric("Drafted Notice Replies", len(r_data))
        
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
# TAB 2: SEARCH
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
            results = judgments
            
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
                    
                    file_ids = str(row.get("PDF File IDs", "")).split(",")
                    if file_ids and file_ids[0] != "":
                        st.markdown("**Attachments:**")
                        for idx, fid in enumerate(file_ids):
                            if fid.strip():
                                file_bytes = download_from_gcs(fid.strip())
                                if file_bytes:
                                    st.download_button(label=f"⬇️ Download PDF {idx+1}", data=file_bytes, file_name=fid.strip(), mime="application/pdf", key=f"dl_{fid}")
    except Exception as e:
        st.warning("Could not fetch records.")

# ==========================================
# TAB 3: ADD NEW JUDGMENT
# ==========================================
with tab_add:
    st.header("1. Upload & AI Auto-Fill")
    uploaded_files = st.file_uploader("Upload Judgments (PDF)", type=["pdf"], accept_multiple_files=True)
    
    if st.button("🤖 AI: Read PDFs & Auto-Fill"):
        if uploaded_files:
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
            st.warning("Upload files first.")

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
        
        if st.form_submit_button("✅ Upload & Save to Cloud"):
            if case_name and brief_facts and decision_held:
                with st.spinner("Uploading to Google Cloud Storage and saving to Sheets..."):
                    j_id = str(int(time.time()))
                    gcs_file_ids = []
                    if uploaded_files:
                        for f in uploaded_files:
                            file_buffer = BytesIO(f.getbuffer())
                            fid = upload_to_gcs(file_buffer, f"{j_id}_{f.name}")
                            if fid: gcs_file_ids.append(fid)
                    
                    row_data = [j_id, case_name, act_name, section_num, authority, brief_facts, decision_held, ",".join(gcs_file_ids), ai_notes, status]
                    sh.worksheet("Judgments").append_row(row_data)
                    st.session_state.form_data = {k: "" for k in st.session_state.form_data}
                    st.success("Saved successfully to the Cloud!")

# ==========================================
# TAB 4: QUICK LINK (Original Link Feature)
# ==========================================
with tab_link:
    st.header("Quick Link Precedent to Internal Matter")
    try:
        judgments = sh.worksheet("Judgments").get_all_records()
        if judgments:
            j_dict = {f"{r['Status']} {r['Case Name']}": r for r in judgments}
            selected_j = st.selectbox("Select Precedent", options=list(j_dict.keys()))
            internal_case_name = st.text_input("Internal Matter / Client Name *", key="quick_matter")
            notes = st.text_area("Your Strategy/Notes", height=100, key="quick_notes")
            
            if st.button("Process & Save Link", key="quick_btn"):
                if internal_case_name:
                    usage_id = str(int(time.time()))
                    row_data = [usage_id, str(j_dict[selected_j]['ID']), internal_case_name, "N/A", notes, "N/A"]
                    sh.worksheet("Internal Usage").append_row(row_data)
                    st.success("Linked in Google Sheets!")
        else:
            st.info("No judgments found.")
    except Exception as e:
        st.error("Error connecting to Google Sheets.")

# ==========================================
# TAB 5: DRAFT NOTICE REPLY (NEW FEATURE)
# ==========================================
with tab_reply:
    st.header("📝 Step 1: Analyze Notice & Find Precedents")
    notice_files = st.file_uploader("Upload Legal Notice(s) received (PDF)", type=["pdf"], accept_multiple_files=True, key="notice_uploader")
    
    if st.button("🔍 Read Notice & Suggest Judgments"):
        if notice_files:
            with st.spinner("Reading Notice and searching Knowledge Bank..."):
                st.session_state.notice_text = extract_text_from_buffers(notice_files)
                
                # Fetch all Good Law judgments from DB
                all_judgments = sh.worksheet("Judgments").get_all_records()
                good_law_catalog = ""
                for j in all_judgments:
                    if "Good Law" in j.get("Status", ""):
                        good_law_catalog += f"ID: {j['ID']} | Case: {j['Case Name']} | Facts: {j['Brief Facts']} | Decision: {j['Decision Held']}\n\n"
                
                prompt = f"""
                You are a senior litigation attorney. 
                Read this legal notice: {st.session_state.notice_text[:15000]}
                
                Here is a catalog of precedents in our firm's database:
                {good_law_catalog[:30000]}
                
                Identify the best precedents to use to defend against or reply to this notice. 
                Return ONLY a valid JSON list of the exact Case Names you recommend. Example: ["Case A", "Case B"]
                """
                res, err = ask_ai(prompt)
                
                if not err:
                    try:
                        suggested_names = json.loads(res.replace("```json", "").replace("```", "").strip())
                        st.session_state.suggested_cases = suggested_names
                        st.success("Analysis complete! See suggestions below.")
                    except:
                        st.warning("AI suggested cases, but formatting was slightly off. Please select manually below.")
        else:
            st.warning("Please upload a notice first.")

    st.markdown("---")
    st.header("📝 Step 2: Build Your Argument")
    
    try:
        all_judgments = sh.worksheet("Judgments").get_all_records()
        all_case_names = [j['Case Name'] for j in all_judgments]
        
        # Pre-select the cases the AI suggested (if they exist in the DB)
        default_selections = [c for c in st.session_state.suggested_cases if c in all_case_names]
        
        selected_internal = st.multiselect("Select Internal Precedents to include:", options=all_case_names, default=default_selections)
        
        st.markdown("**Add External References (Optional):**")
        external_refs = st.text_area("Type any outside case laws or specific arguments you want included in the draft:")
        
        if st.button("✍️ Draft Reply"):
            if st.session_state.notice_text:
                with st.spinner("Drafting your response..."):
                    # Gather full details of selected internal cases
                    selected_details = ""
                    for j in all_judgments:
                        if j['Case Name'] in selected_internal:
                            selected_details += f"Case: {j['Case Name']}\nRuling: {j['Decision Held']}\n\n"
                    
                    draft_prompt = f"""
                    You are an expert legal counsel. Draft a formal, professional legal reply to the following notice.
                    
                    Original Notice received:
                    {st.session_state.notice_text[:15000]}
                    
                    You MUST cite and apply these internal precedents to support our position:
                    {selected_details}
                    
                    You MUST ALSO incorporate these specific external notes/references:
                    {external_refs}
                    
                    Draft the full body of the legal reply. Use standard legal formatting and authoritative tone.
                    """
                    
                    draft_res, err = ask_ai(draft_prompt)
                    if not err:
                        st.session_state.drafted_reply = draft_res
            else:
                st.error("Please upload and analyze a Notice in Step 1 first.")

    except Exception as e:
        st.error("Error loading precedents.")

    st.markdown("---")
    st.header("📝 Step 3: Review, Edit, and Save")
    
    matter_name = st.text_input("Matter / Client Name (For tracking):")
    final_draft = st.text_area("Edit your Final Reply:", value=st.session_state.drafted_reply, height=400)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("💾 Save Record to Knowledge Bank"):
            if matter_name and final_draft:
                with st.spinner("Saving to Google Sheets..."):
                    record_id = str(int(time.time()))
                    row_data = [
                        record_id, 
                        matter_name, 
                        st.session_state.notice_text, 
                        ", ".join(selected_internal), 
                        external_refs, 
                        final_draft
                    ]
                    sh.worksheet("Notice Replies").append_row(row_data)
                    st.success("Notice and Reply successfully recorded!")
            else:
                st.error("Please provide a Matter Name and ensure the draft is not empty.")
    
    with col2:
        if final_draft:
            docx_file = create_word_docx(final_draft, f"Reply to Notice - {matter_name}")
            st.download_button("📄 Download Reply as Word (.docx)", data=docx_file, file_name=f"Draft_Reply_{matter_name}.docx")

# ==========================================
# TAB 6: CHAT WITH PDF
# ==========================================
with tab_chat:
    st.header("💬 Interactive Q&A with Judgments")
    try:
        chat_judgments = [row for row in sh.worksheet("Judgments").get_all_records() if row.get("PDF File IDs")]
        if chat_judgments:
            c_dict = {r['Case Name']: r for r in chat_judgments}
            selected_chat_j = st.selectbox("Select a Judgment to Chat with:", options=list(c_dict.keys()))
            
            user_question = st.text_input("Ask a question about this specific judgment:")
            if st.button("Ask AI", key="chat_btn"):
                if user_question:
                    with st.spinner("Fetching PDF from Cloud Storage and analyzing..."):
                        file_ids = str(c_dict[selected_chat_j]["PDF File IDs"]).split(",")
                        doc_text = ""
                        for fid in file_ids:
                            if fid.strip():
                                pdf_bytes = download_from_gcs(fid.strip())
                                if pdf_bytes:
                                    reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
                                    for page in reader.pages:
                                        doc_text += page.extract_text() + "\n"
                        
                        if doc_text:
                            prompt = f"Based ONLY on the following legal judgment text, answer this question: {user_question}\n\nJudgment Text:\n{doc_text[:35000]}"
                            answer, err = ask_ai(prompt)
                            if not err:
                                st.session_state.chat_history.append({"q": user_question, "a": answer})
                        else:
                            st.error("Could not extract text from the Cloud Storage files.")
            for chat in reversed(st.session_state.chat_history):
                st.markdown(f"**🧑‍⚖️ You:** {chat['q']}")
                st.info(f"**🤖 AI:** {chat['a']}")
                st.markdown("---")
    except Exception as e:
        st.warning("Error fetching data.")