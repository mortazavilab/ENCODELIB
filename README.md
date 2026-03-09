# ENCODELIB 🔬

**ENCODE Library & Server** — A lightweight Python interface to the ENCODE Portal API plus a small `fastmcp` server that exposes convenient experiment- and file-discovery tools.

---

## 🚀 Quick overview

- **Library:** `encodeLib.py` provides `ENCODE` and `encodeExperiment` classes for searching experiments, retrieving metadata, and organizing/downloading files from ENCODE. Includes retry logic with exponential backoff and parallel file downloads.
- **Server:** `encode_server.py` exposes the library via `fastmcp` tools and runs on `http://127.0.0.1:8080`. Supports optional API key authentication.
- **Docs:** `encodeLib.md` contains full usage docs for the library. `SERVER_README.md` documents server tools and configuration in detail.

---

## 📁 Repository structure

- `encodeLib.py` — Main ENCODE library implementation (classes & helpers).
- `encodeLib.md` — Full library documentation and examples (recommended read).
- `encode_server.py` — `fastmcp` server exposing library functionality as tools.
- `start-server.sh` — Startup script to run the server (auto-installs server deps if missing).
- `SERVER_README.md` — Server-specific README with endpoints, tools and troubleshooting.

---
## 🧩 Client (Streamlit) 📱

The repository includes a Streamlit-based client `encodeStream.py` (interactive UI and LLM-assisted workflow). Full client documentation and running instructions are available in `CLIENT_README.md`.

## ⚙️ Installation & prerequisites

1. Ensure Python 3.8+ is installed.

2. Install recommended packages. The server expects `fastmcp`; the library works with common packages such as `requests` and `pandas` (some features use `pandas` for DataFrame helpers).

Example (server):

```bash
# Server dependencies should be listed in a requirements file (e.g. requirements-server.txt)
pip install fastmcp requests pandas
```

Tip: If you plan to run the included server, use the provided `start-server.sh` script — it looks for `python` or `python3` and installs `requirements-server.txt` if needed.

---

## ▶️ Quick usage

### Library (python)

```python
from encodeLib import ENCODE
encode = ENCODE()                      # loads experiments (uses cache)
hits = encode.search_experiments_by_biosample('K562', assay_title='TF ChIP-seq')
exp = encode.getExperiment('ENCSR000CDC')
print(exp.get_file_types())

# Look up an experiment from a file accession (works for any ENCFF)
exp = encode.search_experiments_by_file_accession('ENCFF001RJK')

# Get metadata / download URL for any file (experiment files, genome refs, etc.)
meta = encode.get_file_metadata('ENCFF001RJK')
url  = encode.get_file_url('ENCFF001RJK')
```

See `encodeLib.md` for comprehensive examples and API docs (search, file discovery, caching, downloads).

### Server (fastmcp)

Start the server (recommended):

```bash
chmod +x start-server.sh
./start-server.sh
```

Or run directly:

```bash
python3 encode_server.py
# or
fastmcp run encode_server.py
```

The server exposes tools such as `search_by_biosample`, `search_by_target`, `get_files_by_type`, `download_files`, and the new file-accession tools `search_by_file_accession`, `get_file_metadata_by_accession`, and `get_file_url_by_accession` — see `SERVER_README.md` for details and examples.

---

## 🧰 Notes about caching & files

- The library/server use a local cache directory: `.encode_cache/` (created in working directory).
- Metadata is cached per-experiment (hierarchical structure) to speed repeat operations.
- Downloaded files are stored under `./files/{accession}/`.



## 📜 License ✅

This project is licensed under the **MIT License**. See the `LICENSE` file for the full license text.
