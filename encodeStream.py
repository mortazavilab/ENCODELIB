import streamlit as st
import requests
import json
import os
import uuid
import sys
import argparse
from datetime import datetime

# ==========================================
# ⚙️ CONFIGURATION & CLI PARSING
# ==========================================
SESSION_FILE = "chat_sessions.json"
SETTINGS_FILE = "settings.json"
DEFAULT_IP = "127.0.0.1" # Safe local default
MODEL_CHOICES = ["devstral-small-2:latest", "mistral:latest", "llama3.1:latest"]

def get_cli_args():
    """Parses command line arguments passed after '--'."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, help="Initial Server IP address")
    # Streamlit passes its own args, so we parse known args and ignore others
    args, _ = parser.parse_known_args()
    return args

st.set_page_config(page_title="ENCODE Analyst", layout="wide", page_icon="🧬")

# ==========================================
# 💾 SETTINGS MANAGER
# ==========================================

def load_settings():
    """Loads settings, prioritizing CLI args first, then disk, then defaults."""
    cli_args = get_cli_args()
    
    # Base defaults
    settings = {
        "servers": [{"name": "Localhost", "ip": "127.0.0.1"}],
        "active_server_ip": DEFAULT_IP
    }
    
    # Load from disk if exists
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                disk_settings = json.load(f)
                settings.update(disk_settings)
        except:
            pass

    # CLI Override (Ephemeral override, doesn't save to disk immediately unless user acts)
    if cli_args.ip:
        # Check if this IP exists in known servers, if not add it temp
        known_ips = [s["ip"] for s in settings["servers"]]
        if cli_args.ip not in known_ips:
            settings["servers"].insert(0, {"name": f"CLI Server ({cli_args.ip})", "ip": cli_args.ip})
        settings["active_server_ip"] = cli_args.ip
        
    return settings

def save_settings(settings):
    """Writes settings to disk."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def get_active_urls():
    """Constructs URLs dynamically based on current session state or settings."""
    # Use session state if available (real-time switching), else load from disk
    if "active_server_ip" in st.session_state:
        ip = st.session_state.active_server_ip
    else:
        settings = load_settings()
        ip = settings["active_server_ip"]
        st.session_state.active_server_ip = ip # Sync state
        
    return {
        "mcp": f"http://{ip}:8080/mcp",
        "ollama": f"http://{ip}:11434/api/chat",
        "ip": ip
    }

# ==========================================
# 💾 SESSION MANAGER (Chats)
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
        if "New Chat" in sessions[s_id]["name"] and len(st.session_state.messages) > 1:
            first_msg = next((m["content"] for m in st.session_state.messages if m["role"] == "user"), None)
            if first_msg: sessions[s_id]["name"] = first_msg[:30] + "..."
        save_all_sessions(sessions)

# ==========================================
# 🔌 MCP PROTOCOL
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
        for line in lines:
            if line.strip().startswith("data:"):
                try: return json.loads(line.strip()[5:])
                except: pass
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def extract_raw_result(rpc_response):
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

def get_available_tools_schema():
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
    clean = []
    for msg in messages:
        if msg["role"] in ["user", "assistant", "system"]:
            new_m = {"role": msg["role"], "content": msg.get("content", "") or ""}
            if msg.get("tool_calls"): new_m["tool_calls"] = msg["tool_calls"]
            clean.append(new_m)
        elif msg["role"] == "tool_result":
            content_val = msg["content"]
            if not isinstance(content_val, str): content_val = json.dumps(content_val)
            clean.append({"role": "tool", "content": content_val})
    return clean

def chat_with_ollama(model, messages, tools=None):
    urls = get_active_urls()
    clean_history = sanitize_messages_for_ollama(messages)
    payload = {"model": model, "messages": clean_history, "stream": False}
    if tools: payload["tools"] = tools

    try:
        res = requests.post(urls["ollama"], json=payload)
        res.raise_for_status()
        return res.json()["message"]
    except Exception as e:
        return {"role": "assistant", "content": f"⚠️ LLM Error: {str(e)}"}

# ==========================================
# 🖥️ STREAMLIT UI & SIDEBAR
# ==========================================

# 1. Initialize State
if "active_session_id" not in st.session_state:
    existing = load_all_sessions()
    if existing:
        st.session_state.active_session_id = list(existing.keys())[0]
        st.session_state.messages = existing[st.session_state.active_session_id]["messages"]
    else:
        create_new_session()

# Load Settings (CLI > Disk)
if "settings_loaded" not in st.session_state:
    settings = load_settings()
    st.session_state.active_server_ip = settings["active_server_ip"]
    st.session_state.server_list = settings["servers"]
    st.session_state.settings_loaded = True

# 2. Sidebar
with st.sidebar:
    st.header("🗂️ Chat History")
    if st.button("➕ New Chat", use_container_width=True):
        create_new_session()
    
    st.divider()
    
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
            if st.button("🗑️", key=f"del_{s_id}"):
                delete_session(s_id)
    
    st.divider()
    
    # --- SERVER SETTINGS UI ---
    st.header("⚙️ Server Settings")
    
    # Dropdown for Active Server
    server_list = st.session_state.server_list
    active_ip = st.session_state.active_server_ip
    
    server_names = [s["name"] for s in server_list]
    
    # Determine index, default to first if active IP not found
    try:
        active_name = next((s["name"] for s in server_list if s["ip"] == active_ip), server_names[0])
        idx = server_names.index(active_name)
    except:
        idx = 0
        
    selected_server_name = st.selectbox("Active Server", server_names, index=idx)
    
    # Handle Server Switch
    new_ip = next((s["ip"] for s in server_list if s["name"] == selected_server_name), active_ip)
    
    if new_ip != active_ip:
        st.session_state.active_server_ip = new_ip
        # Save to disk
        save_settings({"servers": server_list, "active_server_ip": new_ip})
        # Reset connection
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.success(f"Switched to {selected_server_name}")
        st.rerun()

    # Expandable Manager
    with st.expander("Manage Servers"):
        st.caption("Add a new MCP server connection.")
        new_svr_name = st.text_input("Name", placeholder="Remote GPU")
        new_svr_ip = st.text_input("IP Address", placeholder="128.200.7.223")
        
        if st.button("Add Server"):
            if new_svr_name and new_svr_ip:
                server_list.insert(0, {"name": new_svr_name, "ip": new_svr_ip})
                st.session_state.server_list = server_list
                st.session_state.active_server_ip = new_svr_ip
                save_settings({"servers": server_list, "active_server_ip": new_svr_ip})
                st.rerun()
        
        if st.button("🗑️ Remove Selected"):
            if len(server_list) > 1:
                st.session_state.server_list = [s for s in server_list if s["name"] != selected_server_name]
                st.session_state.active_server_ip = st.session_state.server_list[0]["ip"]
                save_settings({"servers": st.session_state.server_list, "active_server_ip": st.session_state.active_server_ip})
                st.rerun()
            else:
                st.error("Cannot delete last server.")

    st.divider()
    st.subheader("Chat Options")
    
    current_name = all_sessions[st.session_state.active_session_id]["name"]
    new_name = st.text_input("Rename Chat", value=current_name)
    if new_name != current_name:
        rename_session(st.session_state.active_session_id, new_name)
        
    selected_model = st.selectbox("LLM Model", MODEL_CHOICES)
    
    if st.button("🔄 Force Reconnect"):
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

# 3. Main Interface
st.title("🧬 ENCODE Analyst")
active_urls = get_active_urls()

# Auto-connect if history empty
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

# Display Messages
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"): st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        with st.chat_message("assistant"):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    st.code(f"🛠️ Tool Call: {tc['function']['name']}", language="text")
    elif msg["role"] == "tool_result":
        with st.chat_message("assistant", avatar="📦"):
            with st.expander(f"📦 Raw Output: {msg.get('name')}", expanded=False):
                st.json(msg["content"])

# Input Loop
if prompt := st.chat_input("Ex: 'Search for human lung experiments'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    save_current_interaction()
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        if not get_mcp_session():
            st.error(f"Cannot reach server at {active_urls['ip']}")
            st.stop()

        ollama_tools, _ = get_available_tools_schema()
        
        # 1. Intent
        with st.spinner(f"Thinking ({selected_model})..."):
            response = chat_with_ollama(selected_model, st.session_state.messages, ollama_tools)
        
        if response.get("content"): st.markdown(response["content"])
        
        # 2. Tools
        if response.get("tool_calls"):
            st.session_state.messages.append(response)
            save_current_interaction()
            
            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                st.code(f"🛠️ Calling: {fn_name}\nArgs: {fn_args}", language="json")
                
                with st.spinner("Fetching data..."):
                    raw_res = mcp_rpc_call("tools/call", {"name": fn_name, "arguments": fn_args})
                    data = extract_raw_result(raw_res)
                
                with st.chat_message("assistant", avatar="📦"):
                    with st.expander(f"📦 Raw Output: {fn_name}", expanded=False):
                        st.json(data)
                
                st.session_state.messages.append({
                    "role": "tool_result",
                    "name": fn_name,
                    "content": data
                })
                save_current_interaction()
            
            # 3. Summary
            with st.spinner("Analyzing..."):
                final_res = chat_with_ollama(selected_model, st.session_state.messages)
            
            st.markdown(final_res["content"])
            st.session_state.messages.append(final_res)
            save_current_interaction()
        else:
            st.session_state.messages.append(response)
            save_current_interaction()