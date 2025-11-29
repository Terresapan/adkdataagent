import streamlit as st
import os
import queue
import time
import uuid
from google.adk import Client, types
import google.genai.types as genai_types
from main import initialize_backend, process_user_message, is_backend_initialized
from utils import check_password

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="Data Analysis Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- STYLING INJECTION ---
st.markdown("""
<style>
    .stChatMessage {
        background-color: transparent !important;
    }
    .stChatInput {
        padding-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# --- PASSWORD CHECK ---
if not check_password():
    st.stop()

# --- SIDEBAR: CONFIGURATION & UPLOAD ---
with st.sidebar:
    st.title("🔧 Configuration")
    
    # Model Selection
    selected_model = st.radio(
        "Select Model",
        ["gemini-2.5-flash", "gemini-2.5-pro"],
        index=0,
        help="Choose the Gemini model for analysis."
    )
    
    # Check if model changed
    if "model_name" not in st.session_state:
        st.session_state.model_name = selected_model
    elif st.session_state.model_name != selected_model:
        st.session_state.model_name = selected_model
        st.session_state.backend_initialized = False # Force re-init
        st.rerun()

    # API Key Setup
    if "backend_initialized" not in st.session_state or not st.session_state.backend_initialized:
        if "llmapikey" in st.secrets and "GOOGLE_API_KEY" in st.secrets["llmapikey"]:
            os.environ["GOOGLE_API_KEY"] = st.secrets["llmapikey"]["GOOGLE_API_KEY"]
        
        # Pass the selected model to initialize_backend
        if initialize_backend(os.environ.get("GOOGLE_API_KEY", ""), model_name=st.session_state.model_name):
            st.session_state.backend_initialized = True
            st.session_state.messages = []
            st.success(f"Connected: {st.session_state.model_name}", icon="✅")
        else:
            st.error("Backend Connection Failed. Check API Key.")
    else:
        st.success(f"Active: {st.session_state.model_name}", icon="🟢")

    st.divider()
    
    st.header("📂 Data Source")
    uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"], help="Upload a dataset for the agent to analyze.")
    
    file_context = ""
    
    # Handle File Upload Logic
    if uploaded_file is not None:
        if "current_file_name" not in st.session_state or st.session_state.current_file_name != uploaded_file.name:
            os.makedirs("uploads", exist_ok=True)
            file_path = os.path.join("uploads", uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            try:
                client = Client(api_key=os.environ["GOOGLE_API_KEY"])
                with st.spinner(f"🚀 Uploading {uploaded_file.name} to Gemini..."):
                    genai_file = client.files.upload(file=file_path, config=types.FileDict(display_name=uploaded_file.name))
                
                st.session_state.uploaded_file_uri = genai_file.uri
                st.session_state.uploaded_file_name = genai_file.name 
                st.session_state.current_file_name = uploaded_file.name
                st.toast(f"File uploaded: {uploaded_file.name}", icon="✅")
                
            except Exception as e:
                st.error(f"Upload Error: {e}")
                if "uploaded_file_uri" in st.session_state: del st.session_state.uploaded_file_uri
        else:
            st.caption(f"✅ Active: **{st.session_state.current_file_name}**")

        # Generate context string
        abs_path = os.path.abspath(os.path.join("uploads", uploaded_file.name))
        file_context = f"\n\n[System Note: User file uploaded. Local path: {abs_path}. Prefer using the attached File API resource.]"

    elif "current_file_name" in st.session_state:
        st.info(f"Using previously uploaded: **{st.session_state.current_file_name}**")

    st.divider()
    if st.button("Clear Conversation", icon="🗑️"):
        st.session_state.messages = []
        st.rerun()

# --- MAIN AREA ---
st.title("📊 Data Analysis Agent")
st.markdown("Ask questions about your data, generate plots, and download PDF reports.")

# --- HISTORY RENDERER ---
for msg in st.session_state.messages:
    avatar = "assets/bot01.jpg" if msg["role"] == "assistant" else "👤"
    with st.chat_message(msg["role"], avatar=avatar):
        if "parts" in msg:
            for part in msg["parts"]:
                if part["type"] == "thought":
                     with st.status("Thinking Process", state="complete", expanded=False):
                        st.markdown(part["content"])
                elif part["type"] == "text":
                    st.markdown(part["content"])
                elif part["type"] == "code":
                    with st.expander("View Code", expanded=False):
                        st.code(part["content"], language="python")
                elif part["type"] == "image":
                    st.image(part["data"], caption="Generated Plot", width="content") # Updated
                elif part["type"] == "pdf":
                    st.download_button(
                        label=f"📄 Download {part['name']}", 
                        data=part["data"], 
                        file_name=part["name"], 
                        mime="application/pdf", 
                        key=part.get("key", str(uuid.uuid4()))
                    )

# --- CHAT INPUT ---
if prompt := st.chat_input("What insights do you need from the data?"):
    full_prompt = prompt + file_context
    
    # Construct Message Content
    if "uploaded_file_uri" in st.session_state:
        message_content = [
            genai_types.Part(text=full_prompt),
            genai_types.Part(file_data=genai_types.FileData(file_uri=st.session_state.uploaded_file_uri, mime_type="text/csv"))
        ]
    else:
        message_content = full_prompt

    st.session_state.messages.append({"role": "user", "content": prompt, "parts": [{"type": "text", "content": prompt}]})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="assets/bot01.jpg"):
        # Initial Status
        status_container = st.empty()
        with status_container.status("🚀 Starting analysis...", expanded=True) as s:
            
            response_parts = []
            data_queue = queue.Queue()
            media_buffer = [] 
            
            # Start Processing
            thread = process_user_message(message_content, data_queue)

            current_type = None
            current_placeholder = None
            current_content = ""
            current_container = None
            streaming_active = False

            while True:
                try:
                    item_type, data = data_queue.get(timeout=0.1)
                    
                    if not streaming_active and item_type != "done":
                        streaming_active = True
                        s.update(label="🧠 Analyzing data...", state="running")

                    if item_type == "done":
                        break
                    if item_type == "error":
                        st.error(data)
                        continue

                    # --- 1. THOUGHTS (Hidden in Status) ---
                    if item_type == "thought":
                        st.write(data) # Write thoughts inside the status container
                        # We don't add thoughts to the main chat history to keep it clean, 
                        # OR we can add them as collapsed items later. 
                        # Let's add them to history but not render them in the main flow during stream to avoid jumpiness
                        if response_parts and response_parts[-1]["type"] == "thought":
                            response_parts[-1]["content"] += data + "\n"
                        else:
                            response_parts.append({"type": "thought", "content": data + "\n"})

                    # --- 2. CODE (Hidden in Status or Separate) ---
                    elif item_type in ["code", "code_output"]:
                        st.code(data, language="python" if item_type=="code" else None)
                        if response_parts and response_parts[-1]["type"] == "code":
                            response_parts[-1]["content"] += data + "\n"
                        else:
                            response_parts.append({"type": "code", "content": data + "\n"})

                    # --- 3. TEXT (Main Output) ---
                    elif item_type == "text":
                        # Ensure we break out of the status container for the main text
                        if current_container != "main":
                            # Close/Complete the status container if we are switching to main text
                            s.update(label="✅ Analysis complete", state="complete", expanded=False)
                            current_container = "main"
                            current_placeholder = st.empty()
                            current_content = ""
                            response_parts.append({"type": "text", "content": ""})
                        
                        current_content += data
                        current_placeholder.markdown(current_content + "▌")
                        response_parts[-1]["content"] = current_content

                    # --- 4. MEDIA BUFFERING ---
                    elif item_type == "image":
                        media_buffer.append({"type": "image", "data": data})
                    elif item_type == "pdf":
                        media_buffer.append({"type": "pdf", "data": data})

                except queue.Empty:
                    if not thread.is_alive(): break
                    continue

            thread.join()
            s.update(label="✅ Complete", state="complete", expanded=False)
            
            if current_type == "text" and current_placeholder:
                current_placeholder.markdown(current_content) # Remove cursor

            # --- RENDER BUFFERED MEDIA ---
            for media_item in media_buffer:
                if media_item["type"] == "image":
                    st.image(media_item["data"], caption="Generated Plot", width="content") # Updated
                    response_parts.append({"type": "image", "data": media_item["data"]})
                
                elif media_item["type"] == "pdf":
                    fname = f"report_{int(time.time())}.pdf"
                    unique_key = f"dl_{fname}_{uuid.uuid4()}"
                    st.download_button(
                        label=f"📄 Download {fname}", 
                        data=media_item["data"], 
                        file_name=fname, 
                        mime="application/pdf", 
                        key=unique_key
                    )
                    response_parts.append({
                        "type": "pdf", 
                        "data": media_item["data"], 
                        "name": fname, 
                        "key": unique_key 
                    })

            st.session_state.messages.append({"role": "assistant", "parts": response_parts})