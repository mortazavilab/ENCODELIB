# ENCODELIB 🔬

**ENCODE Library & Server** — A lightweight Python interface to the ENCODE Portal API plus a small `fastmcp` server that exposes convenient experiment- and file-discovery tools.

---

## 🚀 Quick overview

- **Library:** `encodeLib.py` provides `ENCODE` and `encodeExperiment` classes for searching experiments, retrieving metadata, and organizing/downloading files from ENCODE.
- **Server:** `encode_server.py` exposes the library via `fastmcp` tools and runs on `http://127.0.0.1:8080`.
- **Docs:** `encodeLib.md` contains full usage docs for the library. `SERVER_README.md` documents server tools and configuration in detail.

---

## 📁 Repository structure

- `encodeLib.py` — Main ENCODE library implementation (classes & helpers).
- `encodeLib.md` — Full library documentation and examples (recommended read).
- `encode_server.py` — `fastmcp` server exposing library functionality as tools.
- `start-server.sh` — Startup script to run the server (auto-installs server deps if missing).
- `SERVER_README.md` — Server-specific README with endpoints, tools and troubleshooting.

---

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

The server exposes tools such as `search_by_biosample`, `search_by_target`, `get_files_by_type`, `download_files`, and cache management utilities — see `SERVER_README.md` for details and examples.

---

## 🧰 Notes about caching & files

- The library/server use a local cache directory: `.encode_cache/` (created in working directory).
- Metadata is cached per-experiment (hierarchical structure) to speed repeat operations.
- Downloaded files are stored under `./files/{accession}/`.

---

## 🧪 Development & contributions

- Add issues or pull requests for bugs or features.
- Follow established code style and add tests where appropriate.

> If you want to add or change server tools, decorate functions in `encode_server.py` with `@server.tool()` (see `SERVER_README.md` for examples).

---

## ⚠️ Missing items to consider



## Contact

For questions about the implementation or API, see the docs in `encodeLib.md` or open an issue in this repository.


## 📜 License ✅

This project is licensed under the **MIT License**. See the `LICENSE` file for the full license text.


Thanks — this README is intended as a concise entry point; tell me if you want a longer README with badges, CI instructions, or an explicit `requirements-server.txt` file added. ✅
