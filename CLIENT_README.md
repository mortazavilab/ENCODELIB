# ENCODE Client — Streamlit UI (ENCODE Analyst)

A lightweight Streamlit-based client for interacting with the ENCODE fastmcp server.

This client (`encodeStream.py`) provides a conversational interface powered by an LLM and integrates MCP tool calls for searching experiments, retrieving metadata, and visualizing results. It can talk to either a local Ollama server or an OpenAI-compatible chat endpoint such as LM Studio.

---

## 🔧 Requirements

- Python 3.8+
- streamlit
- requests
- pandas
- An LLM endpoint if you want model-assisted analysis locally or remotely
  - Ollama example: `http://127.0.0.1:11434`
  - LM Studio example: `http://127.0.0.1:1234/v1`

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
- Supports auth-enabled ENCODE server deployments with a session-scoped sidebar API key

---

## ⚙️ Configuration & UI

- Sidebar
  - Chat history and session management (create, rename, delete)
  - Server selection / management (add remote servers by IP)
  - LLM provider selector (`Ollama` or `OpenAI-Compatible`)
  - LLM base URL field (for example `http://127.0.0.1:11434` or `http://127.0.0.1:1234/v1`)
  - Session-scoped API key field for auth-enabled MCP servers
  - Analysis parameters: Temperature, Seed, Top-P
  - Model selection (Ollama models) and Force Reconnect button

- Main chat view
  - Quick Actions tabs for explicit `search_batch`, `get_experiment_facets`, `export_experiments`, `get_performance_stats`, `get_search_index_stats`, and `rebuild_search_index` calls
  - Conversation history (user, assistant, tool-results)
  - Tool outputs are shown as expandable boxes with structured display (DataFrame or JSON)
  - Chat input accepts natural language queries like: _"Search for human lung experiments"_

Files used by the client:
- `chat_sessions.json` — persisted chat sessions
- `settings.json` — persisted server list and analysis parameters

Server API keys are kept in Streamlit session state only and are not written to `settings.json`.

---

## 💡 How tool calls work (brief)

1. User submits prompt
2. The client acquires an MCP session (initialize) if needed
3. It requests tool schemas from the server, then sends the conversation to the configured LLM endpoint
4. If the LLM returns tool calls, the client executes them via the MCP `tools/call` endpoint
5. Tool results are appended to context, and the LLM is asked to synthesize a final answer (streamed if possible)

The Quick Actions panel uses the same MCP endpoint directly, so you can run the v0.4 batch, facet, export, and metrics/index tools even when you do not want to rely on model-selected tool calls.

When a Server API Key is set in the sidebar, the client injects it automatically into MCP tool calls for both Quick Actions and LLM-triggered tool execution. Rendered tool-call transcripts redact the key before displaying or saving chat state.

For Ollama, the client uses `/api/chat` and `/api/tags`. For OpenAI-compatible endpoints such as LM Studio, it uses `/chat/completions` and `/models` under the configured base URL.

This flow allows for reliable combination of programmatic data access (via MCP) and natural language synthesis (via the configured LLM backend).

---

## 🛡️ Safeguards & Notes

- Data visualizations cap interactive rows to avoid UI freezes (first 50 rows displayed)
- For large tool results, the client computes and passes simple statistics to the LLM (counts per column such as `assay`, `biosample`, `organism`) to keep answers accurate for aggregates
- If the server is unreachable, the client shows a connection error and retains session state for retry
- API keys entered in the sidebar are hidden in the UI and remain local to the current Streamlit session

---

## Example workflow

1. Start server: `./start-server.sh`
2. Start client: `streamlit run encodeStream.py`
3. In the sidebar, choose an LLM provider and base URL if you are not using the default local Ollama setup
4. Enter prompt: `Find TP53 ChIP-seq experiments in human K562 cells`
5. Watch assistant call tools, display results, and return a synthesis (with counts and example rows)

---

## Development tips

- Add/modify tool handling by changing `get_available_tools_schema()` and `extract_raw_result()` logic
- To test against a remote server, add its IP in the sidebar or use CLI `--ip`
- To use LM Studio, set provider to `OpenAI-Compatible` and base URL to something like `http://127.0.0.1:1234/v1`

---

## License

Client code in this repo is covered by the project `LICENSE` (MIT).