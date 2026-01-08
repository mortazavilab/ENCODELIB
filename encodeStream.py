import streamlit as st
import requests
import json
import os
import uuid
import argparse
import pandas as pd
from datetime import datetime


__version__ = "0.2"

# ==========================================
# ⚙️ CONFIGURATION & DEFAULTS
# ==========================================
SESSION_FILE = "chat_sessions.json"
SETTINGS_FILE = "settings.json"
DEFAULT_IP = "127.0.0.1"

# REPRODUCIBILITY DEFAULTS
DEFAULT_TEMP = 0.0   # Strict adherence to facts
DEFAULT_SEED = 42    # Fixed seed for same-output-every-time
DEFAULT_TOP_P = 0.2  # Low randomness in token selection

def get_cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, help="Initial Server IP address")
    args, _ = parser.parse_known_args()
    return args

st.set_page_config(page_title="ENCODE Analyst", layout="wide", page_icon="🧬")

# ==========================================
# 💾 SETTINGS MANAGER
# ==========================================

def load_settings():
    cli_args = get_cli_args()
    
    settings = {
        "servers": [{"name": "Localhost", "ip": "127.0.0.1"}],
        "active_server_ip": DEFAULT_IP,
        "temperature": DEFAULT_TEMP,
        "seed": DEFAULT_SEED,
        "top_p": DEFAULT_TOP_P
    }
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                disk_settings = json.load(f)
                settings.update(disk_settings)
        except:
            pass

    if cli_args.ip:
        known_ips = [s["ip"] for s in settings["servers"]]
        if cli_args.ip not in known_ips:
            settings["servers"].insert(0, {"name": f"CLI Server ({cli_args.ip})", "ip": cli_args.ip})
        settings["active_server_ip"] = cli_args.ip
        
    return settings

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_active_urls():
    if "active_server_ip" in st.session_state:
        ip = st.session_state.active_server_ip
    else:
        settings = load_settings()
        ip = settings["active_server_ip"]
        st.session_state.active_server_ip = ip
        
    return {
        "mcp": f"http://{ip}:8080/mcp",
        "ollama": f"http://{ip}:11434/api/chat",
        "tags": f"http://{ip}:11434/api/tags",
        "ip": ip
    }

# ==========================================
# 💾 SESSION MANAGER
# ==========================================

def load_all_sessions():
    if not os.path.exists(SESSION_FILE): return {}
    try:
        with open(SESSION_FILE, "r") as f: return json.load(f)
    except: return {}

def save_all_sessions(sessions):
    with open(SESSION_FILE, "w") as f: json.dump(sessions, f, indent=2)

def create_new_session():
    new_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    sessions = load_all_sessions()
    sessions[new_id] = {
        "name": f"New Chat ({timestamp})",
        "created_at": timestamp,
        "messages": []
    }
    save_all_sessions(sessions)
    st.session_state.active_session_id = new_id
    st.session_state.messages = []
    st.rerun()

def delete_session(session_id):
    sessions = load_all_sessions()
    if session_id in sessions:
        del sessions[session_id]
        save_all_sessions(sessions)
        if st.session_state.active_session_id == session_id:
            del st.session_state.active_session_id
            st.rerun()
        else:
            st.rerun()

def rename_session(session_id, new_name):
    sessions = load_all_sessions()
    if session_id in sessions:
        sessions[session_id]["name"] = new_name
        save_all_sessions(sessions)
        st.rerun()

def save_current_interaction():
    if "active_session_id" not in st.session_state: return
    sessions = load_all_sessions()
    s_id = st.session_state.active_session_id
    if s_id in sessions:
        sessions[s_id]["messages"] = st.session_state.messages
        # Auto-rename new chats based on first user message
        if "New Chat" in sessions[s_id]["name"] and len(st.session_state.messages) > 0:
            first_msg = next((m["content"] for m in st.session_state.messages if m["role"] == "user"), None)
            if first_msg: sessions[s_id]["name"] = first_msg[:30] + "..."
        save_all_sessions(sessions)

# ==========================================
# 🔌 MCP PROTOCOL & TOOLS
# ==========================================

def get_mcp_session():
    if "mcp_session_id" in st.session_state:
        return st.session_state.mcp_session_id

    urls = get_active_urls()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0", "method": "initialize", "id": 1,
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "streamlit", "version": "1.0"}}
    }

    try:
        resp = requests.post(urls["mcp"], json=payload, headers=headers, timeout=5)
        resp.raise_for_status()
        session_id = resp.headers.get("mcp-session-id")
        if session_id:
            st.session_state.mcp_session_id = session_id
            return session_id
    except Exception:
        return None

def mcp_rpc_call(method, params=None):
    session_id = get_mcp_session()
    if not session_id: return {"error": "No Session ID"}
    
    urls = get_active_urls()
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "mcp-session-id": session_id}
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}

    try:
        resp = requests.post(urls["mcp"], json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        # Handle SSE format (data: ...)
        for line in lines:
            if line.strip().startswith("data:"):
                try: return json.loads(line.strip()[5:])
                except: pass
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def extract_raw_result(rpc_response):
    """Normalize MCP output into a usable object."""
    if not rpc_response or "result" not in rpc_response: return rpc_response
    result = rpc_response["result"]
    if isinstance(result, dict) and "content" in result:
        content_list = result["content"]
        parsed = []
        for item in content_list:
            if item.get("type") == "text":
                try: parsed.append(json.loads(item.get("text", "")))
                except: parsed.append(item.get("text", ""))
        return parsed[0] if len(parsed) == 1 else parsed
    return result

# ==========================================
# 🛠️ OLLAMA HELPER
# ==========================================

def get_ollama_models():
    """Dynamically fetch models installed on the server."""
    urls = get_active_urls()
    try:
        resp = requests.get(urls["tags"], timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except:
        pass
    return ["mistral:latest", "llama3.1:latest"] # Fallback

def get_available_tools_schema():
    """Fetch tools from MCP and convert to OpenAI/Ollama Schema."""
    rpc_res = mcp_rpc_call("tools/list")
    if not rpc_res or "result" not in rpc_res: return [], []
    mcp_tools = rpc_res["result"].get("tools", [])
    ollama_tools = []
    for tool in mcp_tools:
        ollama_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema", {})
            }
        })
    return ollama_tools, mcp_tools

def sanitize_messages_for_ollama(messages):
    """
    1. Injects System Prompt.
    2. 🚀 SMART FIX: If data is truncated, Python calculates the stats 
       (counts of assays/biosamples) and feeds them to the LLM so the 
       answer is mathematically correct.
    """
    
    system_prompt = {
        "role": "system",
        "content": (
            "You are the ENCODE Analyst. "
            "RULES: "
            "1. Use the provided 'Statistical Summary' to answer questions about counts and totals. "
            "2. Use the 'Data Preview' only to understand the structure or specific examples. "
            "3. Format answers in Markdown tables."
        )
    }

    clean = [system_prompt]
    
    for msg in messages:
        if msg["role"] in ["user", "assistant", "system"]:
            # Copy standard text messages
            new_m = {"role": msg["role"], "content": msg.get("content", "") or ""}
            if msg.get("tool_calls"): new_m["tool_calls"] = msg["tool_calls"]
            clean.append(new_m)
            
        elif msg["role"] == "tool_result":
            content_val = msg["content"]
            
            # --- 🚀 SMART SUMMARIZER LOGIC ---
            if isinstance(content_val, list) and len(content_val) > 10 and isinstance(content_val[0], dict):
                try:
                    # 1. Convert to DataFrame for fast counting
                    df = pd.DataFrame(content_val)
                    total_rows = len(df)
                    
                    # 2. Generate Quick Stats (ALL items for key columns, not just top 5)
                    stats_msg = f"**[SYSTEM STATISTICS for {total_rows} TOTAL rows]**\n"
                    
                    # Check for common columns to summarize
                    for col in ["assay", "biosample", "organism", "lab"]:
                        if col in df.columns:
                            # MODIFICATION: Removed .head(5) to include ALL counts
                            counts = df[col].value_counts().to_dict()
                            stats_msg += f"- Complete Counts for {col}: {counts}\n"
                    
                    # 3. Create the Preview (First 5 rows)
                    preview = content_val[:5]
                    preview_json = json.dumps(preview)
                    
                    # 4. Combine into one message for the LLM
                    clean_content = (
                        f"{stats_msg}\n"
                        f"**[DATA PREVIEW - First 5 rows only]:**\n{preview_json}"
                    )
                except:
                    # Fallback if pandas fails
                    preview = content_val[:5]
                    clean_content = json.dumps(preview) + "\n[Note: Data truncated]"
            else:
                # Small data? Send it all.
                clean_content = json.dumps(content_val) if not isinstance(content_val, str) else content_val

            clean.append({"role": "tool", "content": clean_content})
            
    return clean

def chat_generator(model, messages, tools=None):
    """Generator function for Streaming Responses."""
    urls = get_active_urls()
    clean_history = sanitize_messages_for_ollama(messages)
    
    options = {
        "temperature": st.session_state.get("temperature", DEFAULT_TEMP),
        "seed": int(st.session_state.get("seed", DEFAULT_SEED)),
        "top_p": st.session_state.get("top_p", DEFAULT_TOP_P)
    }
    
    payload = {
        "model": model,
        "messages": clean_history,
        "stream": True,  # ENABLE STREAMING
        "options": options
    }
    if tools: 
        payload["tools"] = tools
        payload["stream"] = False # Disable stream if we expect tool calls (simplifies logic)

    try:
        with requests.post(urls["ollama"], json=payload, stream=True) as resp:
            resp.raise_for_status()
            # If not streaming (because tools), return full JSON
            if not payload["stream"]:
                yield resp.json()["message"]
                return

            # If streaming, yield chunks
            for line in resp.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if not chunk.get("done"):
                        content = chunk["message"].get("content", "")
                        yield content
    except Exception as e:
        yield f"⚠️ Error: {str(e)}"

# ==========================================
# 🖥️ STREAMLIT UI & SIDEBAR
# ==========================================

# Initialize Session
if "active_session_id" not in st.session_state:
    existing = load_all_sessions()
    if existing:
        st.session_state.active_session_id = list(existing.keys())[0]
        st.session_state.messages = existing[st.session_state.active_session_id]["messages"]
    else:
        create_new_session()

# Load Settings
if "settings_loaded" not in st.session_state:
    settings = load_settings()
    st.session_state.active_server_ip = settings["active_server_ip"]
    st.session_state.server_list = settings["servers"]
    st.session_state.temperature = settings.get("temperature", DEFAULT_TEMP)
    st.session_state.seed = settings.get("seed", DEFAULT_SEED)
    st.session_state.top_p = settings.get("top_p", DEFAULT_TOP_P)
    st.session_state.settings_loaded = True

with st.sidebar:
    st.header("🗂️ Chat History")
    if st.button("➕ New Chat", use_container_width=True):
        create_new_session()
    
    st.divider()
    
    # Chat History List
    all_sessions = load_all_sessions()
    sorted_sessions = sorted(all_sessions.items(), key=lambda x: x[1]['created_at'], reverse=True)
    
    for s_id, s_data in sorted_sessions:
        col1, col2 = st.columns([0.8, 0.2])
        is_active = (s_id == st.session_state.active_session_id)
        label = f"**{s_data['name']}**" if is_active else s_data['name']
        with col1:
            if st.button(label, key=f"btn_{s_id}", use_container_width=True):
                st.session_state.active_session_id = s_id
                st.session_state.messages = s_data["messages"]
                st.rerun()
        with col2:
            if st.button("🗑️", key=f"del_{s_id}"): delete_session(s_id)
    
    st.divider()
    
    # --- SERVER SETTINGS ---
    st.header("⚙️ Server")
    server_list = st.session_state.server_list
    active_ip = st.session_state.active_server_ip
    server_names = [s["name"] for s in server_list]
    
    try:
        active_name = next((s["name"] for s in server_list if s["ip"] == active_ip), server_names[0])
        idx = server_names.index(active_name)
    except: idx = 0
        
    selected_server_name = st.selectbox("Active Server", server_names, index=idx)
    new_ip = next((s["ip"] for s in server_list if s["name"] == selected_server_name), active_ip)
    
    if new_ip != active_ip:
        st.session_state.active_server_ip = new_ip
        curr = load_settings()
        curr["active_server_ip"] = new_ip
        save_settings(curr)
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

    with st.expander("Manage Servers"):
        new_svr_name = st.text_input("Name", placeholder="Remote GPU")
        new_svr_ip = st.text_input("IP Address", placeholder="128.200.7.223")
        
        if st.button("Add Server"):
            if new_svr_name and new_svr_ip:
                server_list.insert(0, {"name": new_svr_name, "ip": new_svr_ip})
                st.session_state.server_list = server_list
                st.session_state.active_server_ip = new_svr_ip
                save_settings(load_settings() | {"servers": server_list, "active_server_ip": new_svr_ip})
                st.rerun()
        
    st.divider()
    
    # --- ANALYSIS PARAMETERS ---
    st.header("🔬 Parameters")
    
    # 1. Temperature
    new_temp = st.slider("Temperature", 0.0, 1.0, st.session_state.temperature, 0.05, help="0.0 = Deterministic (Recommended), 1.0 = Creative")
    # 2. Seed
    new_seed = st.number_input("Random Seed", value=int(st.session_state.seed))
    # 3. Top-P
    new_top_p = st.slider("Top-P", 0.0, 1.0, st.session_state.top_p, 0.05)

    if (new_temp != st.session_state.temperature or 
        new_seed != st.session_state.seed or 
        new_top_p != st.session_state.top_p):
        
        st.session_state.temperature = new_temp
        st.session_state.seed = new_seed
        st.session_state.top_p = new_top_p
        
        curr = load_settings()
        curr.update({
            "temperature": new_temp,
            "seed": new_seed,
            "top_p": new_top_p
        })
        save_settings(curr)

    st.divider()
    
    # --- CHAT UTILS ---
    # Dynamic Model Loading
    available_models = get_ollama_models()
    selected_model = st.selectbox("LLM Model", available_models)
    
    if st.button("🔄 Force Reconnect"):
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

# 3. Main Interface
st.title("🧬 ENCODE Analyst")
active_urls = get_active_urls()

# Connection Status & Welcome
if not st.session_state.messages:
    with st.spinner(f"Connecting to {active_urls['ip']}..."):
        if get_mcp_session():
            _, raw_tools = get_available_tools_schema()
            if raw_tools:
                welcome = f"### 🟢 Connected to {selected_server_name}\n**Available Tools:**\n\n"
                for t in raw_tools:
                    welcome += f"- **`{t['name']}`**: {t.get('description','').splitlines()[0]}\n"
                st.session_state.messages.append({"role": "assistant", "content": welcome})
                save_current_interaction()
        else:
            st.session_state.messages.append({"role": "assistant", "content": f"⚠️ **Connection Failed**: Could not reach {active_urls['ip']}."})

# -------------------------------------
# 💬 RENDER MESSAGE HISTORY
# -------------------------------------

def visualize_data(data):
    """
    Optimized: Converts JSON to DataFrame but strictly limits row count 
    to prevent UI freezing on large datasets.
    """
    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
        try:
            df = pd.DataFrame(data)
            row_count = len(df)
            
            # 🚀 PERFORMANCE FIX: Limit UI to 50 rows
            if row_count > 50:
                st.dataframe(df.head(50))
                st.caption(f"⚠️ Displaying first 50 of {row_count} rows to save memory.")
            else:
                st.dataframe(df)
            return True
        except:
            return False
    return False

for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"): st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        with st.chat_message("assistant"):
            if msg.get("content"):
                st.markdown(msg["content"])
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    st.code(f"🛠️ Tool Call: {tc['function']['name']}", language="text")
    elif msg["role"] == "tool_result":
        with st.chat_message("assistant", avatar="📦"):
            with st.expander(f"📦 Output: {msg.get('name')}", expanded=False):
                if not visualize_data(msg["content"]):
                    st.json(msg["content"])

# -------------------------------------
# 🗣️ CHAT INPUT HANDLER
# -------------------------------------

if prompt := st.chat_input("Ex: 'Search for human lung experiments'"):
    # 1. Append User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_current_interaction()
    with st.chat_message("user"): st.markdown(prompt)

    # 2. Assistant Response Logic
    with st.chat_message("assistant"):
        if not get_mcp_session():
            st.error(f"Cannot reach server at {active_urls['ip']}")
            st.stop()

        ollama_tools, _ = get_available_tools_schema()
        
        # --- ROUND 1: INTENT & TOOL SELECTION ---
        # We use the generator here, but since tools are passed, it returns a dict immediately (no stream)
        response_gen = chat_generator(selected_model, st.session_state.messages, ollama_tools)
        response = next(response_gen) # Get single response object
        
        # Display Text (if model chats before using tools)
        if response.get("content"):
            st.markdown(response["content"])

        # --- ROUND 2: TOOL EXECUTION ---
        if response.get("tool_calls"):
            # Append the Assistant's "Intent" message to history
            st.session_state.messages.append(response)
            save_current_interaction()
            
            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                st.code(f"🛠️ Calling: {fn_name}\nArgs: {fn_args}", language="json")
                
                with st.spinner("Fetching data..."):
                    raw_res = mcp_rpc_call("tools/call", {"name": fn_name, "arguments": fn_args})
                    data = extract_raw_result(raw_res)
                
                # Show Result
                with st.chat_message("assistant", avatar="📦"):
                      with st.expander(f"📦 Output: {fn_name}", expanded=True):
                        if not visualize_data(data):
                            st.json(data)
                
                # Append Tool Result to history
                st.session_state.messages.append({
                    "role": "tool_result",
                    "name": fn_name,
                    "content": data
                })
                save_current_interaction()
            
            # --- ROUND 3: FINAL SUMMARY (STREAMING) ---
            # Now we call chat_generator WITHOUT tools to get the final synthesis stream
            stream = chat_generator(selected_model, st.session_state.messages)
            final_content = st.write_stream(stream)
            
            # Append final answer to history
            st.session_state.messages.append({"role": "assistant", "content": final_content})
            save_current_interaction()

        else:
            # If no tools were called, the response content is already in 'response'
            # But since we didn't stream it above (because tools were enabled), we just append it.
            if response.get("content"):
                st.session_state.messages.append(response)
                save_current_interaction()