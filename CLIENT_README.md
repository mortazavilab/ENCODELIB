# ENCODE Client — Streamlit UI (ENCODE Analyst)

A lightweight Streamlit-based client for interacting with the ENCODE fastmcp server.

This client (`encodeStream.py`) provides a conversational interface powered by an LLM (via Ollama or similar) and integrates MCP tool calls for searching experiments, retrieving metadata, and visualizing results.

---

## 🔧 Requirements

- Python 3.8+
- streamlit
- requests
- pandas
- Ollama (optional) if you want LLM assistance locally

Install with pip:

```bash
pip install streamlit requests pandas
# Optional: Ollama server for local LLMs
# https://ollama.com/
```

---

## ▶️ Running the client

1. Start the ENCODE fastmcp server (see `start-server.sh` / `SERVER_README.md`).

2. Run the Streamlit client:

```bash
streamlit run encodeStream.py
```

3. The client opens in your browser (default Streamlit port: `http://localhost:8501`).

You can pass a custom server IP to the client:

```bash
streamlit run encodeStream.py -- --ip 128.200.7.223
```

> Note: the client communicates with the ENCODE MCP server on port `8080` (MCP endpoint `http://{ip}:8080/mcp`).

---

## 🧭 What the client does

- Connects to a running ENCODE `fastmcp` server and lists available MCP tools
- Lets you chat with an LLM (if available) to ask questions about experiments and datasets
- When the model decides to call one or more MCP tools, the client executes them and shows the returned data
- Provides lightweight visualization (pandas DataFrame) with safeguards against very large results
- Saves chat sessions locally in `chat_sessions.json` and settings in `settings.json`

---

## ⚙️ Configuration & UI

- Sidebar
  - Chat history and session management (create, rename, delete)
  - Server selection / management (add remote servers by IP)
  - Analysis parameters: Temperature, Seed, Top-P
  - Model selection (Ollama models) and Force Reconnect button

- Main chat view
  - Conversation history (user, assistant, tool-results)
  - Tool outputs are shown as expandable boxes with structured display (DataFrame or JSON)
  - Chat input accepts natural language queries like: _"Search for human lung experiments"_

Files used by the client:
- `chat_sessions.json` — persisted chat sessions
- `settings.json` — persisted server list and analysis parameters

---

## 💡 How tool calls work (brief)

1. User submits prompt
2. The client acquires an MCP session (initialize) if needed
3. It requests tool schemas from the server, then sends the conversation to the LLM
4. If the LLM returns tool calls, the client executes them via the MCP `tools/call` endpoint
5. Tool results are appended to context, and the LLM is asked to synthesize a final answer (streamed if possible)

This flow allows for reliable combination of programmatic data access (via MCP) and natural language synthesis (via LLM).

---

## 🛡️ Safeguards & Notes

- Data visualizations cap interactive rows to avoid UI freezes (first 50 rows displayed)
- For large tool results, the client computes and passes simple statistics to the LLM (counts per column such as `assay`, `biosample`, `organism`) to keep answers accurate for aggregates
- If the server is unreachable, the client shows a connection error and retains session state for retry

---

## Example workflow

1. Start server: `./start-server.sh`
2. Start client: `streamlit run encodeStream.py`
3. Enter prompt: `Find TP53 ChIP-seq experiments in human K562 cells`
4. Watch assistant call tools, display results, and return a synthesis (with counts and example rows)

---

## Development tips

- Add/modify tool handling by changing `get_available_tools_schema()` and `extract_raw_result()` logic
- To test against a remote server, add its IP in the sidebar or use CLI `--ip`

---

## License

Client code in this repo is covered by the project `LICENSE` (MIT).