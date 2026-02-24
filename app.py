import streamlit as st
import sqlite3
import os
import time
import PyPDF2
import json
import shutil
import pandas as pd
import plotly.express as px
from io import BytesIO
from docx import Document
from google import genai

# --- Configuration & Setup ---
DB_NAME = "legal_knowledge_bank.db"
PDF_DIR = "uploaded_pdfs"

st.set_page_config(page_title="Enterprise Legal Knowledge Bank", layout="wide", page_icon="🏛️")

# Sidebar for API Key
st.sidebar.header("⚙️ Settings")
api_key = st.sidebar.text_input("Enter Gemini API Key (for AI features):", type="password")
if api_key:
    st.sidebar.success("✅ API Key registered!")

def init_db():
    if not os.path.exists(PDF_DIR):
        os.makedirs(PDF_DIR)
        
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Updated to include STATUS
    c.execute('''
        CREATE TABLE IF NOT EXISTS judgments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_name TEXT NOT NULL,
            act_name TEXT,
            section_number TEXT,
            authority TEXT,
            brief_facts TEXT,
            decision_held TEXT,
            pdf_filenames TEXT, 
            ai_notes TEXT,
            status TEXT DEFAULT '🟢 Good Law'
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS internal_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            judgment_id INTEGER,
            internal_case_name TEXT NOT NULL,
            internal_notice TEXT,
            usage_notes TEXT,
            ai_brief TEXT,
            FOREIGN KEY(judgment_id) REFERENCES judgments(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    return sqlite3.connect(DB_NAME)

def extract_text_from_pdfs(pdf_filenames):
    """Extracts text from saved PDF files for Chat feature."""
    text = ""
    for f_name in pdf_filenames:
        f_path = os.path.join(PDF_DIR, f_name)
        if os.path.exists(f_path):
            try:
                reader = PyPDF2.PdfReader(f_path)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
            except Exception as e:
                pass
    return text

def extract_text_from_buffers(pdf_buffers):
    """Extracts text from uploaded PDF buffers."""
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
    """Generates a downloadable Word Document."""
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
st.title("🏛️ Enterprise Legal Knowledge Bank")

tab_dash, tab_search, tab_add, tab_link, tab_chat, tab_admin = st.tabs([
    "📊 Dashboard", "🔍 Search", "➕ Add Judgment", "🔗 Link & Draft", "💬 Chat with PDF", "⚙️ Backup & Admin"
])

# ==========================================
# TAB 1: DASHBOARD & ANALYTICS
# ==========================================
with tab_dash:
    st.header("Firm Knowledge Analytics")
    conn = get_db_connection()
    total_judgments = conn.execute("SELECT COUNT(*) FROM judgments").fetchone()[0]
    total_internal = conn.execute("SELECT COUNT(*) FROM internal_usage").fetchone()[0]
    
    col1, col2 = st.columns(2)
    col1.metric("Total Judgments Banked", total_judgments)
    col2.metric("Internal Matter Links", total_internal)
    
    if total_judgments > 0:
        st.markdown("---")
        df_acts = pd.read_sql_query("SELECT act_name, COUNT(*) as Count FROM judgments WHERE act_name != '' GROUP BY act_name", conn)
        df_auth = pd.read_sql_query("SELECT authority, COUNT(*) as Count FROM judgments WHERE authority != '' GROUP BY authority", conn)
        df_status = pd.read_sql_query("SELECT status, COUNT(*) as Count FROM judgments GROUP BY status", conn)
        
        c1, c2, c3 = st.columns(3)
        with c1:
            if not df_acts.empty:
                fig1 = px.pie(df_acts, values='Count', names='act_name', title='Judgments by Act', hole=0.4)
                st.plotly_chart(fig1, use_container_width=True)
        with c2:
            if not df_auth.empty:
                fig2 = px.bar(df_auth, x='authority', y='Count', title='Judgments by Authority')
                st.plotly_chart(fig2, use_container_width=True)
        with c3:
            if not df_status.empty:
                fig3 = px.pie(df_status, values='Count', names='status', title='Law Status Distribution')
                st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("Dashboard will populate once you add your first judgment.")
    conn.close()

# ==========================================
# TAB 2: SEARCH & FILTER
# ==========================================
with tab_search:
    st.header("Search and Filter Judgments")
    conn = get_db_connection()
    
    search_term = st.text_input("Universal Search (Case Name, Facts, Decision):")
    query = "SELECT * FROM judgments WHERE 1=1"
    params = []
    
    if search_term:
        query += " AND (case_name LIKE ? OR brief_facts LIKE ? OR decision_held LIKE ?)"
        params.extend([f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"])
        
    results = conn.execute(query, params).fetchall()
    
    if results:
        st.success(f"Found {len(results)} judgment(s).")
        for row in results:
            j_id, c_name, act, sec, auth, facts, decision, pdf_files_str, ai_notes, status = row
            
            with st.expander(f"{status} | {c_name} | {act} - Sec {sec}"):
                if "🛑" in status:
                    st.error("WARNING: This judgment has been marked as Overruled or Bad Law.")
                
                st.markdown(f"**Authority:** {auth}")
                st.markdown(f"**Brief Facts:**\n{facts}")
                st.markdown(f"**Decision Held:**\n{decision}")
                
                # Internal usages
                internal_uses = conn.execute('SELECT internal_case_name, ai_brief FROM internal_usage WHERE judgment_id = ?', (j_id,)).fetchall()
                if internal_uses:
                    st.markdown("---")
                    st.markdown("**📌 Internal Usage:**")
                    for use in internal_uses:
                        st.markdown(f"- Used in: **{use[0]}**")
                        if use[1]:
                            docx_file = create_word_docx(use[1], f"Brief - {c_name}")
                            st.download_button(label="📄 Export Brief to Word", data=docx_file, file_name=f"Brief_{c_name}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"word_{j_id}_{use[0]}")
                
                if pdf_files_str:
                    st.markdown("**Attachments:**")
                    for f_name in pdf_files_str.split(","):
                        if f_name:
                            f_path = os.path.join(PDF_DIR, f_name)
                            if os.path.exists(f_path):
                                with open(f_path, "rb") as file:
                                    st.download_button(label=f"⬇️ Download {f_name.split('_', 1)[-1]}", data=file, file_name=f_name.split('_', 1)[-1], mime="application/pdf", key=f"dl_{j_id}_{f_name}")
    conn.close()

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

    st.header("2. Review & Save")
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
        
        if st.form_submit_button("✅ Save to Database"):
            if case_name and brief_facts and decision_held:
                saved_filenames = []
                if uploaded_files:
                    for f in uploaded_files:
                        fname = f"{int(time.time())}_{f.name}"
                        with open(os.path.join(PDF_DIR, fname), "wb") as disk_file:
                            disk_file.write(f.getbuffer())
                        saved_filenames.append(fname)
                
                conn = get_db_connection()
                conn.execute('''
                    INSERT INTO judgments (case_name, act_name, section_number, authority, brief_facts, decision_held, pdf_filenames, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (case_name, act_name, section_num, authority, brief_facts, decision_held, ",".join(saved_filenames), status))
                conn.commit()
                conn.close()
                st.session_state.form_data = {k: "" for k in st.session_state.form_data}
                st.success("Saved successfully!")

# ==========================================
# TAB 4: LINK TO INTERNAL CASE
# ==========================================
with tab_link:
    st.header("Mark Judgment & Draft AI Brief")
    conn = get_db_connection()
    judgments = conn.execute('SELECT id, case_name, brief_facts, decision_held, status FROM judgments').fetchall()
    
    if judgments:
        j_dict = {f"{r[4]} {r[1]}": r for r in judgments}
        selected_j = st.selectbox("Select Precedent", options=list(j_dict.keys()))
        j_data = j_dict[selected_j]
        
        if "🛑" in j_data[4]:
            st.error("⚠️ WARNING: You are attempting to rely on a case marked as OVERRULED/BAD LAW.")
            
        internal_case_name = st.text_input("Internal Matter / Client Name *")
        notice = st.text_area("Legal Notice (Text)", height=150)
        notes = st.text_area("Your Strategy/Notes", height=100)
        draft_ai = st.checkbox("🤖 Use AI to draft brief")
        
        if st.button("Process & Save Link"):
            if internal_case_name:
                ai_brief_text = None
                if draft_ai and notice:
                    with st.spinner("Drafting brief..."):
                        prompt = f"Matter: '{internal_case_name}'. Notice: '{notice}'. Strategy: {notes}. Precedent Facts: {j_data[2]}. Precedent Decision: {j_data[3]}. Draft a professional 3 paragraph legal brief applying precedent to notice."
                        ai_brief_text, err = ask_ai(prompt)
                
                conn.execute('INSERT INTO internal_usage (judgment_id, internal_case_name, internal_notice, usage_notes, ai_brief) VALUES (?, ?, ?, ?, ?)', (j_data[0], internal_case_name, notice, notes, ai_brief_text))
                conn.commit()
                st.success("Linked!")
                if ai_brief_text:
                    st.info(ai_brief_text)
                    docx_file = create_word_docx(ai_brief_text, f"Brief - {internal_case_name}")
                    st.download_button("📄 Download Brief as Word", data=docx_file, file_name=f"Brief_{internal_case_name}.docx")
    conn.close()

# ==========================================
# TAB 5: CHAT WITH PDF
# ==========================================
with tab_chat:
    st.header("💬 Interactive Q&A with Judgments")
    conn = get_db_connection()
    chat_judgments = conn.execute('SELECT id, case_name, pdf_filenames FROM judgments WHERE pdf_filenames IS NOT NULL AND pdf_filenames != ""').fetchall()
    conn.close()
    
    if chat_judgments:
        c_dict = {r[1]: r for r in chat_judgments}
        selected_chat_j = st.selectbox("Select a Judgment to Chat with:", options=list(c_dict.keys()))
        
        user_question = st.text_input("Ask a question about this specific judgment:")
        if st.button("Ask AI"):
            if user_question and api_key:
                with st.spinner("Reading document and generating answer..."):
                    pdf_files = c_dict[selected_chat_j][2].split(",")
                    doc_text = extract_text_from_pdfs(pdf_files)
                    prompt = f"Based ONLY on the following legal judgment text, answer this question: {user_question}\n\nJudgment Text:\n{doc_text[:35000]}"
                    answer, err = ask_ai(prompt)
                    if err:
                        st.error(err)
                    else:
                        st.session_state.chat_history.append({"q": user_question, "a": answer})
            elif not api_key:
                st.warning("API Key required.")
                
        # Display Chat History
        for chat in reversed(st.session_state.chat_history):
            st.markdown(f"**🧑‍⚖️ You:** {chat['q']}")
            st.info(f"**🤖 AI:** {chat['a']}")
            st.markdown("---")
    else:
        st.info("No judgments with PDFs uploaded yet.")

# ==========================================
# TAB 6: BACKUP & ADMIN
# ==========================================
with tab_admin:
    st.header("Local Backup & Restore")
    st.markdown("Protect your data by downloading a full backup of your database and all PDF files. Store this zip file somewhere safe (like a cloud drive or external hard drive).")
    
    if st.button("📦 Generate Full System Backup"):
        with st.spinner("Zipping files..."):
            os.makedirs("temp_backup", exist_ok=True)
            # Copy Database
            if os.path.exists(DB_NAME):
                shutil.copy2(DB_NAME, "temp_backup/")
            # Copy PDFs
            if os.path.exists(PDF_DIR):
                shutil.copytree(PDF_DIR, "temp_backup/uploaded_pdfs", dirs_exist_ok=True)
            
            # Create Zip
            shutil.make_archive("legal_kb_backup", 'zip', "temp_backup")
            
            with open("legal_kb_backup.zip", "rb") as fp:
                st.download_button(
                    label="⬇️ Download Backup Zip",
                    data=fp,
                    file_name=f"Legal_Knowledge_Bank_Backup_{int(time.time())}.zip",
                    mime="application/zip"
                )
                
            # Cleanup temp files
            shutil.rmtree("temp_backup")
            if os.path.exists("legal_kb_backup.zip"):
                os.remove("legal_kb_backup.zip")