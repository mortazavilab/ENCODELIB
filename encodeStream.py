import streamlit as st
import requests
import json
import os
import uuid
import argparse
import pandas as pd
from datetime import datetime

__version__ = "0.4"

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
LLM_PROVIDER_LABELS = {
    "Ollama": "ollama",
    "OpenAI-Compatible": "openai_compatible",
}
DEFAULT_BATCH_QUERY_ROWS = pd.DataFrame([
    {
        "name": "",
        "mode": "biosample",
        "value": "",
        "organism": "",
        "assay_title": "",
        "target": "",
        "exclude_revoked": True,
    }
])

def get_cli_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", type=str, help="Initial Server IP address")
    args, _ = parser.parse_known_args()
    return args

st.set_page_config(page_title="ENCODE Analyst", layout="wide", page_icon="🧬")

def normalize_base_url(url):
    """Normalize user-provided base URLs so endpoint joins stay predictable."""
    return (url or "").strip().rstrip("/")

def get_default_llm_base_url(provider, ip):
    """Return the default base URL for the selected LLM provider."""
    if provider == "openai_compatible":
        return f"http://{ip}:1234/v1"
    return f"http://{ip}:11434"

def get_llm_api_urls(provider, base_url):
    """Resolve chat and model-list endpoints for the active LLM provider."""
    normalized_base = normalize_base_url(base_url)
    if provider == "openai_compatible":
        return {
            "chat": f"{normalized_base}/chat/completions",
            "models": f"{normalized_base}/models",
        }
    return {
        "chat": f"{normalized_base}/api/chat",
        "models": f"{normalized_base}/api/tags",
    }

def get_llm_fallback_models(provider):
    """Return fallback model names when the provider cannot list installed models."""
    if provider == "openai_compatible":
        return ["local-model"]
    return ["mistral:latest", "llama3.1:latest"]

# ==========================================
# 💾 SETTINGS MANAGER
# ==========================================

def load_settings():
    cli_args = get_cli_args()
    
    settings = {
        "servers": [{"name": "Localhost", "ip": "127.0.0.1"}],
        "active_server_ip": DEFAULT_IP,
        "llm_provider": "ollama",
        "llm_base_url": get_default_llm_base_url("ollama", DEFAULT_IP),
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

    settings["llm_provider"] = settings.get("llm_provider", "ollama")
    settings["llm_base_url"] = normalize_base_url(
        settings.get("llm_base_url")
        or get_default_llm_base_url(settings["llm_provider"], settings["active_server_ip"])
    )
        
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

    llm_provider = st.session_state.get("llm_provider")
    llm_base_url = st.session_state.get("llm_base_url")
    if not llm_provider or not llm_base_url:
        settings = load_settings()
        llm_provider = settings.get("llm_provider", "ollama")
        llm_base_url = settings.get("llm_base_url", get_default_llm_base_url(llm_provider, ip))
        st.session_state.llm_provider = llm_provider
        st.session_state.llm_base_url = llm_base_url

    llm_urls = get_llm_api_urls(llm_provider, llm_base_url)
        
    return {
        "mcp": f"http://{ip}:8080/mcp",
        "llm_provider": llm_provider,
        "llm_base_url": normalize_base_url(llm_base_url),
        "llm_chat": llm_urls["chat"],
        "llm_models": llm_urls["models"],
        "ip": ip
    }

# ==========================================
# 💾 SESSION MANAGER
# ==========================================

def load_all_sessions():
    if not os.path.exists(SESSION_FILE): return {}
    try:
        with open(SESSION_FILE, "r") as f:
            sessions = json.load(f)
    except: return {}

    normalized_sessions, changed = normalize_saved_sessions(sessions)
    if changed:
        try:
            save_all_sessions(normalized_sessions)
        except:
            pass
    return normalized_sessions

def save_all_sessions(sessions):
    normalized_sessions, _ = normalize_saved_sessions(sessions)
    with open(SESSION_FILE, "w") as f: json.dump(normalized_sessions, f, indent=2)

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
    normalized_messages, messages_changed = normalize_session_messages(st.session_state.get("messages", []))
    if messages_changed:
        st.session_state.messages = normalized_messages
    sessions = load_all_sessions()
    s_id = st.session_state.active_session_id
    if s_id in sessions:
        sessions[s_id]["messages"] = st.session_state.get("messages", [])
        # Auto-rename new chats based on first user message
        if "New Chat" in sessions[s_id]["name"] and len(st.session_state.get("messages", [])) > 0:
            first_msg = next((m.get("content") for m in st.session_state.get("messages", []) if m.get("role") == "user"), None)
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

def get_api_key_widget_key(server_ip):
    """Build a session-state key for a server-specific API key input."""
    normalized_ip = server_ip.replace(".", "_").replace(":", "_")
    return f"server_api_key_{normalized_ip}"

def get_active_api_key():
    """Return the API key configured for the active server in this session."""
    server_ip = st.session_state.get("active_server_ip", DEFAULT_IP)
    return st.session_state.get(get_api_key_widget_key(server_ip), "").strip()

def build_tool_arguments(arguments=None):
    """Inject the active server API key into MCP tool calls when configured."""
    prepared = dict(arguments or {})
    api_key = get_active_api_key()
    if api_key and not prepared.get("api_key"):
        prepared["api_key"] = api_key
    return prepared

def redact_sensitive_fields(value):
    """Hide sensitive values before rendering or persisting tool-call payloads."""
    if isinstance(value, dict):
        return {
            key: "***redacted***" if key.lower() == "api_key" and item else redact_sensitive_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_fields(item) for item in value]
    return value

def sanitize_assistant_message(message):
    """Remove secrets from assistant tool-call payloads before saving them."""
    if not isinstance(message, dict) or not message.get("tool_calls"):
        return message

    sanitized = dict(message)
    sanitized_calls = []
    for tool_call in message["tool_calls"]:
        cleaned_tool_call = dict(tool_call)
        function = tool_call.get("function")
        if isinstance(function, dict):
            cleaned_function = dict(function)
            cleaned_function["arguments"] = redact_sensitive_fields(function.get("arguments", {}))
            cleaned_tool_call["function"] = cleaned_function
        sanitized_calls.append(cleaned_tool_call)

    sanitized["tool_calls"] = sanitized_calls
    return sanitized

def infer_message_role(message):
    """Infer the client-side message role for legacy or malformed session entries."""
    if not isinstance(message, dict):
        return None

    role = message.get("role")
    if role in {"user", "assistant", "system", "tool_result"}:
        return role
    if role == "tool":
        return "tool_result"
    if message.get("tool_calls") is not None:
        return "assistant"
    if message.get("name") and message.get("content") is not None:
        return "tool_result"
    if message.get("content") is not None:
        return "assistant"
    return None

def normalize_session_message(message):
    """Normalize one stored session message into the client's expected shape."""
    role = infer_message_role(message)
    if role is None:
        return None

    normalized = dict(message)
    normalized["role"] = role

    if role in {"user", "assistant", "system"}:
        normalized["content"] = normalized.get("content", "") or ""
    elif role == "tool_result" and "content" not in normalized:
        normalized["content"] = {}

    if role == "assistant":
        normalized = sanitize_assistant_message(normalized)

    return normalized

def normalize_session_messages(messages):
    """Normalize a session message list and report whether any entry changed."""
    if not isinstance(messages, list):
        return [], True

    normalized_messages = []
    changed = False
    for message in messages:
        normalized = normalize_session_message(message)
        if normalized is None:
            changed = True
            continue
        if normalized != message:
            changed = True
        normalized_messages.append(normalized)

    return normalized_messages, changed

def normalize_saved_sessions(sessions):
    """Normalize all persisted sessions before they are rendered or re-saved."""
    if not isinstance(sessions, dict):
        return {}, True

    normalized_sessions = {}
    changed = False
    for session_id, session_data in sessions.items():
        if not isinstance(session_data, dict):
            changed = True
            continue

        normalized_data = dict(session_data)
        normalized_messages, messages_changed = normalize_session_messages(session_data.get("messages", []))
        normalized_data["messages"] = normalized_messages
        if normalized_data != session_data or messages_changed:
            changed = True
        normalized_sessions[session_id] = normalized_data

    return normalized_sessions, changed

def normalize_mcp_tool_arguments(tool_name, arguments):
    """Repair common malformed tool arguments before display or dispatch."""
    if not isinstance(arguments, dict):
        return arguments if arguments is not None else {}

    normalized_arguments = dict(arguments)
    if tool_name == "search_batch" and isinstance(normalized_arguments.get("queries"), list):
        normalized_queries = []
        for index, query in enumerate(normalized_arguments["queries"], start=1):
            if not isinstance(query, dict):
                continue

            normalized_query = {
                key: value
                for key, value in query.items()
                if value is not None
            }

            mode = normalize_form_value(normalized_query.get("mode"))
            value = normalize_form_value(normalized_query.get("value"))
            search_term = normalize_form_value(normalized_query.get("search_term"))
            organism = normalize_form_value(normalized_query.get("organism"))
            target = normalize_form_value(normalized_query.get("target"))

            if not mode:
                if target and not (search_term or value):
                    mode = "target"
                elif organism and not (search_term or value):
                    mode = "organism"
                else:
                    mode = "biosample"
                normalized_query["mode"] = mode

            if mode == "biosample":
                if search_term and not value:
                    normalized_query["value"] = search_term
                elif value and not search_term:
                    normalized_query["search_term"] = value
            elif mode == "organism":
                if not value and organism:
                    normalized_query["value"] = organism
                if not organism and value:
                    normalized_query["organism"] = value
            elif mode == "target":
                if not value and target:
                    normalized_query["value"] = target
                if not target and value:
                    normalized_query["target"] = value

            normalized_query.setdefault("name", f"query_{index}")
            normalized_queries.append(normalized_query)

        normalized_arguments["queries"] = normalized_queries

    return normalized_arguments

def extract_embedded_tool_calls(content):
    """Parse inline tool-call markup returned by some OpenAI-compatible backends."""
    if not isinstance(content, str) or "call:" not in content:
        return []

    decoder = json.JSONDecoder()
    tool_calls = []
    cursor = 0

    while True:
        call_index = content.find("call:", cursor)
        if call_index == -1:
            break

        name_start = call_index + len("call:")
        brace_index = content.find("{", name_start)
        if brace_index == -1:
            break

        tool_name = content[name_start:brace_index].strip()
        if not tool_name:
            cursor = brace_index + 1
            continue

        try:
            arguments, offset = decoder.raw_decode(content[brace_index:])
        except json.JSONDecodeError:
            cursor = brace_index + 1
            continue

        if isinstance(arguments, dict):
            tool_calls.append({
                "id": None,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": normalize_mcp_tool_arguments(tool_name, arguments),
                },
            })

        cursor = brace_index + offset

    return tool_calls

def format_tool_call(tool_call):
    """Create a readable, redacted tool-call summary for the UI."""
    function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
    safe_arguments = redact_sensitive_fields(function.get("arguments", {}))
    rendered_args = json.dumps(safe_arguments, indent=2, sort_keys=True) if isinstance(safe_arguments, (dict, list)) else str(safe_arguments)
    return f"Tool: {function.get('name', 'unknown')}\nArgs:\n{rendered_args}"

def call_mcp_tool(tool_name, arguments=None):
    """Call a named MCP tool and normalize the response payload."""
    prepared_arguments = normalize_mcp_tool_arguments(tool_name, build_tool_arguments(arguments))
    raw_res = mcp_rpc_call("tools/call", {"name": tool_name, "arguments": prepared_arguments})
    return extract_raw_result(raw_res)

def normalize_form_value(value):
    """Convert empty form fields and NaN values into None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value

def build_batch_queries(query_rows):
    """Convert editable table rows into MCP search_batch query objects."""
    records = query_rows.to_dict("records") if isinstance(query_rows, pd.DataFrame) else query_rows
    queries = []

    for idx, row in enumerate(records, start=1):
        mode = normalize_form_value(row.get("mode")) or "biosample"
        value = normalize_form_value(row.get("value"))

        if not value:
            continue

        query = {
            "name": normalize_form_value(row.get("name")) or f"{mode}_{idx}",
            "mode": mode,
            "value": value,
            "exclude_revoked": bool(row.get("exclude_revoked", True)),
        }

        for key in ["organism", "assay_title", "target"]:
            cleaned = normalize_form_value(row.get(key))
            if cleaned:
                query[key] = cleaned

        queries.append(query)

    return queries

def record_quick_action(tool_name, data):
    """Persist quick-action results in the active chat for follow-up questions."""
    st.session_state.messages.append({
        "role": "assistant",
        "content": f"Quick action executed: `{tool_name}`."
    })
    st.session_state.messages.append({
        "role": "tool_result",
        "name": tool_name,
        "content": data,
    })
    save_current_interaction()

def run_quick_action(tool_name, arguments=None):
    """Execute a UI-triggered MCP tool and save the result into the chat."""
    if not get_mcp_session():
        st.error(f"Cannot reach server at {get_active_urls()['ip']}")
        return None

    with st.spinner(f"Running {tool_name}..."):
        data = call_mcp_tool(tool_name, arguments)

    record_quick_action(tool_name, data)
    return data

# ==========================================
# 🛠️ LLM HELPERS
# ==========================================

def normalize_openai_message(message):
    """Convert OpenAI-compatible chat responses into the client's message shape."""
    normalized = {
        "role": message.get("role", "assistant"),
        "content": message.get("content", "") or "",
    }
    tool_calls = []

    for tool_call in message.get("tool_calls", []):
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw_arguments": arguments}

        tool_name = function.get("name")

        tool_calls.append({
            "id": tool_call.get("id"),
            "type": tool_call.get("type", "function"),
            "function": {
                "name": tool_name,
                "arguments": normalize_mcp_tool_arguments(tool_name, arguments),
            },
        })

    if not tool_calls and normalized["content"]:
        embedded_tool_calls = extract_embedded_tool_calls(normalized["content"])
        if embedded_tool_calls:
            tool_calls = embedded_tool_calls
            normalized["content"] = ""

    if tool_calls:
        normalized["tool_calls"] = tool_calls

    return normalized

def normalize_llm_response(response):
    """Coerce first-round LLM responses into the assistant message shape."""
    if isinstance(response, dict):
        normalized = dict(response)
        normalized.setdefault("role", "assistant")
        normalized.setdefault("content", normalized.get("content", "") or "")
        return normalized
    if isinstance(response, str):
        return {"role": "assistant", "content": response}
    return {"role": "assistant", "content": str(response)}

def get_available_models():
    """Fetch models from the configured LLM provider."""
    urls = get_active_urls()
    provider = urls["llm_provider"]
    try:
        resp = requests.get(urls["llm_models"], timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            if provider == "openai_compatible":
                return [model.get("id") for model in data.get("data", []) if model.get("id")]
            return [model["name"] for model in data.get("models", []) if model.get("name")]
    except:
        pass
    return get_llm_fallback_models(provider)

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

def sanitize_messages_for_llm(messages, provider):
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
            "3. Format answers in Markdown tables. "
            "4. Use MCP tools for data retrieval whenever the user asks for ENCODE data. "
            "5. Prefer the simplest single search tool that answers the user; use search_batch only for explicit multi-query comparisons. "
            "6. For species or assay filters, prefer search_by_organism with organism plus optional search_term, assay_title, or target. "
            "7. For search_batch, every query must include a mode and value. "
            "8. Follow the latest user request exactly and do not carry search terms forward from earlier turns unless the user explicitly asks for refinement."
        )
    }

    clean = [system_prompt]
    
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = msg.get("role")
        if role is None:
            # Backward compatibility: older OpenAI-compatible responses were
            # persisted without a role. Treat tool-call payloads as assistant
            # messages and named content payloads as tool results.
            if msg.get("tool_calls") is not None:
                role = "assistant"
            elif msg.get("name") and msg.get("content") is not None:
                role = "tool_result"
            else:
                continue

        if role in ["user", "assistant", "system"]:
            # Copy standard text messages
            new_m = {"role": role, "content": msg.get("content", "") or ""}
            if provider == "ollama" and msg.get("tool_calls"):
                new_m["tool_calls"] = msg["tool_calls"]
            clean.append(new_m)
            
        elif role == "tool_result":
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

            llm_role = "tool" if provider == "ollama" else "system"
            if provider == "openai_compatible":
                clean_content = f"Tool result ({msg.get('name', 'unknown')}):\n{clean_content}"

            clean.append({"role": llm_role, "content": clean_content})
            
    return clean

def chat_generator(model, messages, tools=None):
    """Generator function for Streaming Responses."""
    urls = get_active_urls()
    provider = urls["llm_provider"]
    clean_history = sanitize_messages_for_llm(messages, provider)
    
    options = {
        "temperature": st.session_state.get("temperature", DEFAULT_TEMP),
        "seed": int(st.session_state.get("seed", DEFAULT_SEED)),
        "top_p": st.session_state.get("top_p", DEFAULT_TOP_P)
    }

    use_stream = tools is None
    if provider == "openai_compatible":
        payload = {
            "model": model,
            "messages": clean_history,
            "stream": use_stream,
            "temperature": options["temperature"],
            "top_p": options["top_p"],
            "seed": options["seed"],
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
    else:
        payload = {
            "model": model,
            "messages": clean_history,
            "stream": use_stream,
            "options": options,
        }
        if tools:
            payload["tools"] = tools

    try:
        with requests.post(urls["llm_chat"], json=payload, stream=use_stream, timeout=120) as resp:
            resp.raise_for_status()
            # If not streaming (because tools), return full JSON
            if not use_stream:
                if provider == "openai_compatible":
                    response_payload = resp.json()
                    choices = response_payload.get("choices", [])
                    message = choices[0].get("message", {}) if choices else {}
                    yield normalize_openai_message(message)
                else:
                    yield resp.json()["message"]
                return

            # If streaming, yield chunks
            for line in resp.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8") if isinstance(line, bytes) else line
                    if provider == "openai_compatible":
                        if not decoded_line.startswith("data:"):
                            continue
                        payload_text = decoded_line[5:].strip()
                        if payload_text == "[DONE]":
                            break
                        chunk = json.loads(payload_text)
                        choices = chunk.get("choices", [])
                        delta = choices[0].get("delta", {}) if choices else {}
                        content = delta.get("content", "")
                        if content:
                            yield content
                    else:
                        chunk = json.loads(decoded_line)
                        if not chunk.get("done"):
                            content = chunk["message"].get("content", "")
                            yield content
    except Exception as e:
        if use_stream:
            yield f"⚠️ Error: {str(e)}"
        else:
            yield {"role": "assistant", "content": f"⚠️ Error: {str(e)}"}

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

normalized_messages, messages_changed = normalize_session_messages(st.session_state.get("messages", []))
if messages_changed:
    st.session_state.messages = normalized_messages
    save_current_interaction()

# Load Settings
if "settings_loaded" not in st.session_state:
    settings = load_settings()
    st.session_state.active_server_ip = settings["active_server_ip"]
    st.session_state.server_list = settings["servers"]
    st.session_state.llm_provider = settings.get("llm_provider", "ollama")
    st.session_state.llm_base_url = settings.get(
        "llm_base_url",
        get_default_llm_base_url(st.session_state.llm_provider, settings["active_server_ip"]),
    )
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
        current_provider = st.session_state.get("llm_provider", "ollama")
        previous_default_llm = get_default_llm_base_url(current_provider, active_ip)
        current_llm_base_url = normalize_base_url(st.session_state.get("llm_base_url", previous_default_llm))
        st.session_state.active_server_ip = new_ip
        curr = load_settings()
        curr["active_server_ip"] = new_ip
        if current_llm_base_url == normalize_base_url(previous_default_llm):
            updated_llm_base_url = get_default_llm_base_url(current_provider, new_ip)
            st.session_state.llm_base_url = updated_llm_base_url
            curr["llm_base_url"] = updated_llm_base_url
        save_settings(curr)
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

    with st.expander("Manage Servers"):
        new_svr_name = st.text_input("Name", placeholder="Remote Server")
        new_svr_ip = st.text_input("IP Address", placeholder="127.0.0.1")
        
        if st.button("Add Server"):
            if new_svr_name and new_svr_ip:
                server_list.insert(0, {"name": new_svr_name, "ip": new_svr_ip})
                st.session_state.server_list = server_list
                st.session_state.active_server_ip = new_svr_ip
                save_settings(load_settings() | {"servers": server_list, "active_server_ip": new_svr_ip})
                st.rerun()

    st.subheader("LLM API")
    provider_labels = list(LLM_PROVIDER_LABELS.keys())
    current_provider = st.session_state.get("llm_provider", "ollama")
    current_provider_label = next(
        (label for label, value in LLM_PROVIDER_LABELS.items() if value == current_provider),
        "Ollama",
    )
    selected_provider_label = st.selectbox(
        "Provider",
        provider_labels,
        index=provider_labels.index(current_provider_label),
    )
    selected_provider = LLM_PROVIDER_LABELS[selected_provider_label]
    if selected_provider != current_provider:
        old_default = get_default_llm_base_url(current_provider, st.session_state.active_server_ip)
        current_base_url = normalize_base_url(st.session_state.get("llm_base_url", old_default))
        new_default = get_default_llm_base_url(selected_provider, st.session_state.active_server_ip)
        st.session_state.llm_provider = selected_provider
        if current_base_url == normalize_base_url(old_default):
            st.session_state.llm_base_url = new_default
        curr = load_settings()
        curr.update({
            "llm_provider": selected_provider,
            "llm_base_url": st.session_state.get("llm_base_url", new_default),
        })
        save_settings(curr)
        st.rerun()

    entered_llm_base_url = st.text_input(
        "Base URL",
        value=st.session_state.get(
            "llm_base_url",
            get_default_llm_base_url(selected_provider, st.session_state.active_server_ip),
        ),
        help="Examples: http://127.0.0.1:11434 for Ollama, http://127.0.0.1:1234/v1 for LM Studio.",
    )
    normalized_llm_base_url = normalize_base_url(entered_llm_base_url)
    if normalized_llm_base_url and normalized_llm_base_url != normalize_base_url(st.session_state.get("llm_base_url", "")):
        st.session_state.llm_base_url = normalized_llm_base_url
        curr = load_settings()
        curr.update({
            "llm_provider": st.session_state.get("llm_provider", selected_provider),
            "llm_base_url": normalized_llm_base_url,
        })
        save_settings(curr)
    st.caption(f"Active LLM endpoint: {normalize_base_url(st.session_state.get('llm_base_url', entered_llm_base_url))}")

    api_key_widget_key = get_api_key_widget_key(st.session_state.active_server_ip)
    st.text_input(
        "Server API Key",
        type="password",
        key=api_key_widget_key,
        help="Passed automatically as api_key on MCP tool calls. Stored only in this Streamlit session.",
    )
    if get_active_api_key():
        st.caption("API key is set for the active server and will be injected into MCP tool calls.")
    else:
        st.caption("Leave blank for servers that do not require API key authentication.")
        
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
    available_models = get_available_models()
    selected_model = st.selectbox("LLM Model", available_models)
    
    if st.button("🔄 Force Reconnect"):
        if "mcp_session_id" in st.session_state: del st.session_state.mcp_session_id
        st.rerun()

# 3. Main Interface
st.title("🧬 ENCODE Analyst")
active_urls = get_active_urls()

if "batch_query_rows" not in st.session_state:
    st.session_state.batch_query_rows = DEFAULT_BATCH_QUERY_ROWS.copy()

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
# ⚡ QUICK ACTIONS
# -------------------------------------

st.subheader("⚡ Quick Actions")
st.caption("Run the v0.4 MCP tools directly. Results are appended to this chat so you can ask follow-up questions without relying on model-driven tool discovery.")

batch_tab, facets_tab, export_tab, metrics_tab = st.tabs([
    "Batch Search",
    "Facets",
    "Export",
    "Metrics",
])

with batch_tab:
    st.caption("Compose multiple biosample, organism, or target searches and run them in a single MCP call.")
    with st.form("quick_batch_search_form"):
        batch_rows = st.data_editor(
            st.session_state.batch_query_rows,
            hide_index=True,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "mode": st.column_config.SelectboxColumn(
                    "Mode",
                    options=["biosample", "organism", "target"],
                    required=True,
                ),
                "exclude_revoked": st.column_config.CheckboxColumn("Exclude Revoked"),
            },
        )
        batch_submit = st.form_submit_button("Run Batch Search", use_container_width=True)

    if batch_submit:
        st.session_state.batch_query_rows = batch_rows
        queries = build_batch_queries(batch_rows)
        if not queries:
            st.error("Add at least one query row with a value before running batch search.")
        else:
            result = run_quick_action("search_batch", {"queries": queries})
            if result is not None and isinstance(result, dict):
                st.success(f"Loaded {len(result)} named result set(s). See the chat history below for details.")

with facets_tab:
    st.caption("Get quick counts for common experiment fields without writing a prompt.")
    with st.form("quick_facets_form"):
        selected_fields = st.multiselect(
            "Facet Fields",
            ["assay_title", "biosample_summary", "organism", "status", "target"],
            default=["assay_title", "organism", "status"],
        )
        facets_submit = st.form_submit_button("Load Facets", use_container_width=True)

    if facets_submit:
        arguments = {"fields": selected_fields} if selected_fields else {}
        result = run_quick_action("get_experiment_facets", arguments)
        if result is not None and isinstance(result, dict):
            st.success(f"Loaded {len(result)} facet group(s). See the chat history below for details.")

with export_tab:
    st.caption("Export all experiments or a filtered subset directly from the client.")
    with st.form("quick_export_form"):
        export_path = st.text_input("Output Path", value="exports/experiments.json")
        export_format = st.selectbox("Format", ["json", "csv", "tsv"], index=0)
        filter_export = st.checkbox("Filter export with a search", value=False)
        search_mode = st.selectbox(
            "Search Mode",
            ["biosample", "organism", "target"],
            disabled=not filter_export,
        )
        search_value = st.text_input(
            "Search Value",
            placeholder="K562, Homo sapiens, CTCF...",
            disabled=not filter_export,
        )
        export_organism = st.text_input("Organism Filter", disabled=not filter_export)
        export_assay = st.text_input("Assay Filter", disabled=not filter_export)
        export_target = st.text_input("Target Filter", disabled=not filter_export)
        export_exclude_revoked = st.checkbox("Exclude Revoked", value=True, disabled=not filter_export)
        export_submit = st.form_submit_button("Export Experiments", use_container_width=True)

    if export_submit:
        export_path = export_path.strip()
        if not export_path:
            st.error("Provide an export path.")
        elif filter_export and not search_value.strip():
            st.error("Provide a search value when filtered export is enabled.")
        else:
            arguments = {
                "filepath": export_path,
                "format": export_format,
            }
            if filter_export:
                arguments.update({
                    "search_mode": search_mode,
                    "search_value": search_value.strip(),
                    "exclude_revoked": export_exclude_revoked,
                })
                if export_organism.strip():
                    arguments["organism"] = export_organism.strip()
                if export_assay.strip():
                    arguments["assay_title"] = export_assay.strip()
                if export_target.strip():
                    arguments["target"] = export_target.strip()

            result = run_quick_action("export_experiments", arguments)
            if result is not None and isinstance(result, dict):
                exported = result.get("exported", "?")
                output_path = result.get("path", export_path)
                st.success(f"Exported {exported} experiment row(s) to {output_path}.")

with metrics_tab:
    st.caption("Inspect server-side performance counters and search-index state.")
    metric_col1, metric_col2, metric_col3 = st.columns(3)

    performance_clicked = metric_col1.button("Performance Stats", key="quick_perf_stats", use_container_width=True)
    index_clicked = metric_col2.button("Index Stats", key="quick_index_stats", use_container_width=True)
    rebuild_clicked = metric_col3.button("Rebuild Index", key="quick_rebuild_index", use_container_width=True)

    if performance_clicked:
        result = run_quick_action("get_performance_stats")
        if result is not None:
            st.success("Performance stats added to the chat history.")

    if index_clicked:
        result = run_quick_action("get_search_index_stats")
        if result is not None:
            st.success("Search index stats added to the chat history.")

    if rebuild_clicked:
        result = run_quick_action("rebuild_search_index")
        if result is not None:
            st.success("Search index rebuild result added to the chat history.")

st.divider()

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
    normalized_msg = normalize_session_message(msg)
    if normalized_msg is None:
        continue

    role = normalized_msg["role"]
    if role == "user":
        with st.chat_message("user"): st.markdown(normalized_msg.get("content", ""))
    elif role == "assistant":
        with st.chat_message("assistant"):
            if normalized_msg.get("content"):
                st.markdown(normalized_msg.get("content", ""))
            if normalized_msg.get("tool_calls"):
                for tc in normalized_msg["tool_calls"]:
                    st.code(format_tool_call(tc), language="text")
    elif role == "tool_result":
        with st.chat_message("assistant", avatar="📦"):
            with st.expander(f"📦 Output: {normalized_msg.get('name')}", expanded=False):
                if not visualize_data(normalized_msg.get("content")):
                    st.json(normalized_msg.get("content"))

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
        response = normalize_llm_response(next(response_gen)) # Get single response object
        
        # Display Text (if model chats before using tools)
        if response.get("content"):
            st.markdown(response["content"])

        # --- ROUND 2: TOOL EXECUTION ---
        if response.get("tool_calls"):
            # Append the Assistant's "Intent" message to history
            st.session_state.messages.append(sanitize_assistant_message(response))
            save_current_interaction()
            
            for tc in response["tool_calls"]:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]
                st.code(format_tool_call(tc), language="text")
                
                with st.spinner("Fetching data..."):
                    data = call_mcp_tool(fn_name, fn_args)
                
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
                st.session_state.messages.append(sanitize_assistant_message(response))
                save_current_interaction()
