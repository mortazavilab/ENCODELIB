# Changelog

## [0.3] - 2025-01-20

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
