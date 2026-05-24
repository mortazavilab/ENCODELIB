# Changelog

## [0.4] - 2026-05-23

### Added
- **Optional experiment loading modes** on `ENCODE`: `load_mode="eager"` (default, backward compatible), `load_mode="lazy"`, and `load_mode="incremental"`.
- **Incremental summary loading** with `load_experiment_summaries()`, `get_experiment_summaries()`, and `load_next_experiment_batch()` to keep lightweight summaries in memory until full experiment payloads are explicitly materialized.
- **Summary cache** stored separately in `experiment_summaries.json` to support incremental and indexed search flows.
- **Optional search indexing** with `build_search_index()`, `clear_search_index()`, and `get_search_index_stats()`.
- **Batch search helper**: `search_experiments_batch()` for grouped biosample, organism, and target searches.
- **Facet helper**: `get_experiment_facets()` for counts by assay, biosample, organism, status, and target.
- **Export helper**: `export_experiments()` for JSON, CSV, and TSV output.
- **Performance reporting**: `get_performance_stats()` with lightweight HTTP/cache/index metrics.
- **Batch file-accession helpers** on `ENCODE`: `get_file_metadata_batch()`, `get_file_url_batch()`, and `search_experiments_by_file_accessions()`.
- **Download manifest and verification support** in `encodeExperiment`: `prepare_download_manifest()`, `preview_only`, `resume`, and `verify_checksum` options.
- **New MCP tools**:
  - `search_batch`
  - `get_experiment_facets`
  - `rebuild_search_index`
  - `get_search_index_stats`
  - `get_performance_stats`
  - `export_experiments`
  - `get_file_metadata_batch_by_accession`
  - `get_file_url_batch_by_accession`
  - `search_by_file_accession_batch`
- **Streamlit client quick actions** for batch search, facets, exports, and metrics/index inspection.
- **Streamlit client LLM provider selection** with configurable base URLs for both Ollama and OpenAI-compatible endpoints such as LM Studio.
- **Focused unit-test coverage** for lazy/incremental loading, indexed search, download preview/resume/checksum behavior, server auth/cache semantics, and server load-mode configuration.

### Changed
- Library version bumped to `0.4`.
- MCP server version bumped to `0.4`.
- Streamlit client version bumped to `0.4`.
- Streamlit client now supports session-scoped API keys for auth-enabled MCP servers and injects them automatically into tool calls.
- Streamlit client can now route model requests to either Ollama (`/api/chat`) or OpenAI-compatible chat APIs (`/chat/completions`) based on sidebar configuration.
- Search methods now reuse `create_experiment_object()` when experiment data is already available, avoiding unnecessary object reconstruction by accession.
- `list_experiments` on the MCP server now uses experiment summaries so low-memory server modes do not have to fully materialize all experiments just to list them.
- `download_files()` now returns a `manifest` alongside download results.
- `_request_with_retry()` now accepts optional request headers, enabling resumable downloads.

### Fixed
- MCP server API-key authentication is now actually enforced across all exposed tools when auth is enabled.
- MCP server cache clearing now resets the shared in-process `ENCODE` singleton so subsequent requests do not reuse stale state.
- `clear_cache(clear_metadata=True)` on the MCP server now clears both the main experiments cache and metadata cache, matching the user-facing message.
- Metadata cache read/write failures now log warnings instead of failing silently.
- Experiment and file API responses now receive basic structure validation before they are cached or returned.
- Streamlit tool-call displays and saved assistant tool-call payloads now redact API keys instead of exposing them in the UI.

### Notes
- `ENCODE()` with no new arguments remains eager-loading by default for backward compatibility.
- In `incremental` mode, direct access to `encode.experiments` still materializes the full experiment list to preserve the existing public API; the low-memory gains come from summary-based search and explicit batch materialization methods.

## [0.3] - 2026-01-20

### Added
- **Retry logic with exponential backoff**: All HTTP requests now automatically retry on transient failures (connection errors, timeouts, HTTP 429/5xx) with configurable max retries and exponential backoff delays.
- **Parallel file downloads**: `encodeExperiment.download_files()` now uses `ThreadPoolExecutor` (default 4 workers) for concurrent downloading. Configurable via `max_workers` parameter.
- **File-accession-level methods on ENCODE class**:
  - `search_experiments_by_file_accession(file_accession)` — find the parent experiment for a given file accession; returns `None` for non-experiment files (genome references, annotations, etc.).
  - `get_file_metadata(file_accession)` — retrieve full metadata for any ENCODE file, with caching.
  - `get_file_url(file_accession)` — get the download URL for any ENCODE file.
  - `_fetch_file_info(file_accession)` — private helper hitting the ENCODE file API with response caching.
- **MCP server authentication**: Optional API key authentication via `--require-api-key` flag and `ENCODE_SERVER_API_KEY` / `ENCODE_REQUIRE_API_KEY` environment variables. Uses `hmac.compare_digest` for constant-time comparison.
- **MCP server CLI arguments**: `--host`, `--port`, `--require-api-key` via `argparse`.
- **Three new MCP server tools**: `search_by_file_accession`, `get_file_metadata_by_accession`, `get_file_url_by_accession`.
- **Type hints**: Full type annotations added to all method signatures in `encodeExperiment` and `ENCODE` classes using `from __future__ import annotations`.
- **Expanded test coverage**: New test classes for retry logic, parallel downloads, file-accession search (experiment files, non-experiment files, caching, validation).

### Changed
- MCP server default bind address changed from `0.0.0.0` to `127.0.0.1` for safer defaults.
- `get_server_info()` MCP tool now includes `auth_required` field and no longer hardcodes host/port.
- All `requests.get()` calls replaced with `_request_with_retry()` throughout the library.

### Fixed
- Removed hardcoded production IP from `tests/test_mcp_server.py`; now defaults to `127.0.0.1`.
- `_get_metadata_cache_path()` now correctly rejects accessions that don't start with `"ENC"` (e.g. `"INVALID"` previously bypassed the length check).
- `TestFileDownloadSecurity.test_filename_sanitization` corrected to reflect actual path-traversal behavior: `os.path.basename('../../../etc/passwd')` → `'passwd'`, so the file is safely sanitized and downloaded rather than rejected. Test now asserts the sanitized file exists in the correct directory and no traversal occurred.

## [0.2] - Initial tracked release

- Core `ENCODE` and `encodeExperiment` classes.
- MCP server (`encode_server.py`) with experiment search, listing, and file tools.
- Streamlit client (`encodeStream.py`).
