import streamlit as st
import requests
import json
import os

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
WATSON_SERVER_IP = "128.200.7.223"
MCP_SERVER_URL = f"http://{WATSON_SERVER_IP}:8080/mcp"
OLLAMA_URL = f"http://{WATSON_SERVER_IP}:11434/api/chat"

MODEL_CHOICES = ["devstral-small-2:latest", "mistral:latest", "llama3.1:latest"]

st.set_page_config(page_title="ENCODE Analyst", layout="wide", page_icon="🧬")

# ==========================================
# 🔌 MCP PROTOCOL
# ==========================================

def get_mcp_session():
    if "mcp_session_id" in st.session_state:
        return st.session_state.mcp_session_id

    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0", "method": "initialize", "id": 1,
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "streamlit", "version": "1.0"}}
    }

    try:
        resp = requests.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=5)
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

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id, 
    }
    payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}

    try:
        resp = requests.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        
        lines = resp.text.strip().split("\n")
        for line in lines:
            if line.strip().startswith("data:"):
                try:
                    return json.loads(line.strip()[5:])
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
    """Cleans history for Ollama API (converts objects to strings, fixes roles)."""
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
    clean_history = sanitize_messages_for_ollama(messages)
    payload = {"model": model, "messages": clean_history, "stream": False}
    if tools: payload["tools"] = tools

    try:
        res = requests.post(OLLAMA_URL, json=payload)
        res.raise_for_status()
        return res.json()["message"]
    except Exception as e:
        return {"role": "assistant", "content": f"⚠️ LLM Error: {str(e)}"}

# ==========================================
# 🖥️ STREAMLIT UI
# ==========================================

with st.sidebar:
    st.header("⚙️ Configuration")
    selected_model = st.selectbox("Model", MODEL_CHOICES)
    if st.button("🔄 Reset Session"):
        st.session_state.messages = []
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

st.title("🧬 ENCODE Analyst")

# Auto-Startup
if "messages" not in st.session_state:
    st.session_state.messages = []
    with st.spinner(f"Connecting to {WATSON_SERVER_IP}..."):
        if get_mcp_session():
            _, raw_tools = get_available_tools_schema()
            if raw_tools:
                welcome = "### 🟢 Server Connected\n**Available Tools:**\n\n"
                for t in raw_tools:
                    welcome += f"- **`{t['name']}`**: {t.get('description','').splitlines()[0]}\n"
                st.session_state.messages.append({"role": "assistant", "content": welcome})

# Render History
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
        # 🔽 THIS IS THE CHANGE FOR HISTORY 🔽
        with st.chat_message("assistant", avatar="📦"):
            with st.expander(f"📦 Raw Output: {msg.get('name')}", expanded=False):
                st.json(msg["content"])

# Input Loop
if prompt := st.chat_input("Ex: 'Search for human lung experiments'"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        if not get_mcp_session():
            st.error("Server Offline")
            st.stop()

        ollama_tools, _ = get_available_tools_schema()
        
        # 1. Get Intent
        with st.spinner(f"Thinking ({selected_model})..."):
            response = chat_with_ollama(selected_model, st.session_state.messages, ollama_tools)
        
        if response.get("content"): st.markdown(response["content"])
        
        # 2. Handle Tools
        if response.get("tool_calls"):
            st.session_state.messages.append(response)
            
            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                st.code(f"🛠️ Calling: {fn_name}\nArgs: {fn_args}", language="json")
                
                with st.spinner("Fetching data..."):
                    raw_res = mcp_rpc_call("tools/call", {"name": fn_name, "arguments": fn_args})
                    data = extract_raw_result(raw_res)
                
                # 🔽 THIS IS THE CHANGE FOR LIVE EXECUTION 🔽
                with st.chat_message("assistant", avatar="📦"):
                    with st.expander(f"📦 Raw Output: {fn_name}", expanded=False):
                        st.json(data)
                
                # Store in History
                st.session_state.messages.append({
                    "role": "tool_result",
                    "name": fn_name,
                    "content": data
                })
            
            # 3. Summarize
            with st.spinner("Analyzing..."):
                final_res = chat_with_ollama(selected_model, st.session_state.messages)
            
            st.markdown(final_res["content"])
            st.session_state.messages.append(final_res)
        else:
            st.session_state.messages.append(response)