#!/usr/bin/env python3
"""
ENCODE fastmcp Server

A fastmcp server exposing ENCODE library functionality.
Default: http://127.0.0.1:8080

Usage:
    python3 encode_server.py
    python3 encode_server.py --host 0.0.0.0 --port 9090
    ENCODE_SERVER_API_KEY=mysecret python3 encode_server.py --require-api-key
"""

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
from fastmcp import FastMCP

from encodeLib import ENCODE, encodeExperiment


__version__ = "0.4"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get the working directory for caching and file storage
WORK_DIR = Path.cwd()
CACHE_DIR = WORK_DIR / ".encode_cache"
FILES_DIR = WORK_DIR / "files"

# Ensure directories exist
CACHE_DIR.mkdir(exist_ok=True)
FILES_DIR.mkdir(exist_ok=True)

# Initialize fastmcp server
server = FastMCP("encode-server")

# Global ENCODE instance (lazily initialized)
_encode_instance = None

# Optional API-key authentication
_REQUIRE_API_KEY = os.environ.get("ENCODE_REQUIRE_API_KEY", "").lower() in ("1", "true", "yes")
_API_KEY = os.environ.get("ENCODE_SERVER_API_KEY", "")
_SERVER_LOAD_MODE = os.environ.get("ENCODE_SERVER_LOAD_MODE", "eager").lower()
_SERVER_INCREMENTAL_BATCH_SIZE = int(os.environ.get("ENCODE_INCREMENTAL_BATCH_SIZE", "250"))
_SERVER_BUILD_INDEX = os.environ.get("ENCODE_BUILD_INDEX", "").lower() in ("1", "true", "yes")
_SERVER_ENABLE_METRICS = os.environ.get("ENCODE_ENABLE_METRICS", "").lower() in ("1", "true", "yes")


def _check_api_key(api_key: Optional[str] = None) -> None:
    """Raise ValueError when auth is required and the key doesn't match."""
    if not _REQUIRE_API_KEY:
        return
    if not _API_KEY:
        # Server operator has not configured a key — skip check
        return
    if not api_key or not isinstance(api_key, str):
        raise ValueError("API key required. Pass api_key parameter.")
    # Constant-time comparison to avoid timing attacks
    import hmac
    if not hmac.compare_digest(api_key, _API_KEY):
        raise ValueError("Invalid API key.")


def get_encode_instance() -> ENCODE:
    """Get or create the global ENCODE instance with custom cache directory."""
    global _encode_instance
    if _encode_instance is None:
        logger.info(f"Initializing ENCODE with cache_dir: {CACHE_DIR}")
        _encode_instance = ENCODE(
            use_cache=True,
            cache_dir=str(CACHE_DIR),
            load_mode=_SERVER_LOAD_MODE,
            incremental_batch_size=_SERVER_INCREMENTAL_BATCH_SIZE,
            build_index=_SERVER_BUILD_INDEX,
            enable_metrics=_SERVER_ENABLE_METRICS,
        )
    return _encode_instance


def _reset_encode_instance() -> None:
    """Drop the cached ENCODE singleton so the next request reloads state."""
    global _encode_instance
    _encode_instance = None


def _serialize_experiment(experiment: encodeExperiment | dict[str, Any], encode: ENCODE) -> dict[str, Any]:
    """Normalize experiment data for MCP responses."""
    if isinstance(experiment, encodeExperiment):
        return {
            "accession": experiment.accession,
            "organism": experiment.organism,
            "assay": experiment.assay,
            "biosample": experiment.biosample,
            "lab": experiment.lab,
            "status": experiment.status,
            "targets": experiment.targets,
            "replicate_count": experiment.replicate_count,
            "description": experiment.description,
            "link": experiment.link,
        }

    return {
        "accession": experiment.get("accession"),
        "organism": encode.get_organism_from_experiment(experiment),
        "assay": experiment.get("assay_title"),
        "biosample": experiment.get("biosample_summary"),
        "lab": experiment.get("lab", {}).get("title", "Unknown") if isinstance(experiment.get("lab"), dict) else experiment.get("lab"),
        "status": experiment.get("status"),
        "targets": encode.get_targets(experiment),
        "replicate_count": len(experiment.get("replicates", [])),
        "description": experiment.get("description", ""),
        "link": f"https://www.encodeproject.org{experiment.get('@id', '')}" if experiment.get("@id") else None,
    }


def _run_search(
    encode: ENCODE,
    *,
    mode: str,
    value: str,
    organism: Optional[str] = None,
    assay_title: Optional[str] = None,
    target: Optional[str] = None,
    exclude_revoked: bool = True,
    return_objects: bool = False,
) -> list[encodeExperiment] | list[dict[str, Any]]:
    """Dispatch a search query to the appropriate ENCODE method."""
    if mode == "biosample":
        return encode.search_experiments_by_biosample(
            value,
            organism=organism,
            assay_title=assay_title,
            target=target,
            exclude_revoked=exclude_revoked,
            return_objects=return_objects,
        )
    if mode == "organism":
        return encode.search_experiments_by_organism(
            value,
            search_term=None,
            assay_title=assay_title,
            target=target,
            exclude_revoked=exclude_revoked,
            return_objects=return_objects,
        )
    if mode == "target":
        return encode.search_experiments_by_target(
            value,
            organism=organism,
            assay_title=assay_title,
            exclude_revoked=exclude_revoked,
            return_objects=return_objects,
        )
    raise ValueError(f"Unsupported search mode: {mode}")


# ============================================================================
# Search Tools
# ============================================================================


@server.tool()
def search_by_biosample(
    search_term: str,
    organism: Optional[str] = None,
    assay_title: Optional[str] = None,
    target: Optional[str] = None,
    exclude_revoked: bool = True,
    api_key: Optional[str] = None,
) -> list[dict]:
    """
    Search for experiments by biosample (cell type, tissue name, or target).
    
    Args:
        search_term: Cell type or tissue name to search for (e.g., 'GM12878', 'K562')
        organism: Optional filter by organism (e.g., 'Homo sapiens')
        assay_title: Optional filter by assay type
        target: Optional filter by target name
        exclude_revoked: Whether to exclude revoked experiments
    
    Returns:
        List of experiment objects with their metadata
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    results = encode.search_experiments_by_biosample(
        search_term,
        organism=organism,
        assay_title=assay_title,
        target=target,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [_serialize_experiment(exp, encode) for exp in results]

@server.tool()
def search_by_organism(
    organism: str,
    search_term: Optional[str] = None,
    assay_title: Optional[str] = None,
    target: Optional[str] = None,
    exclude_revoked: bool = True,
    api_key: Optional[str] = None,
) -> list[dict]:
    """
    Search for experiments by biosample (cell type, tissue name, or target).
    
    Args:
        organism: Organism to search for (e.g., 'Homo sapiens' for human, 'Mus musculus' for mouse)

        assay_title: Optional filter by assay type
        target: Optional filter by target name
        exclude_revoked: Whether to exclude revoked experiments
    
    Returns:
        List of experiment objects with their metadata
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    results = encode.search_experiments_by_organism(
        organism,
        search_term=search_term,
        assay_title=assay_title,
        target=target,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [_serialize_experiment(exp, encode) for exp in results]

@server.tool()
def search_by_target(
    target: str,
    organism: Optional[str] = None,
    assay_title: Optional[str] = None,
    exclude_revoked: bool = True,
    api_key: Optional[str] = None,
) -> list[dict]:
    """
    Search for experiments by target (transcription factor, histone mark, etc.).
    
    Args:
        target: Target name to search for (partial match supported)
        organism: Optional filter by organism
        assay_title: Optional filter by assay type
        exclude_revoked: Whether to exclude revoked experiments
    
    Returns:
        List of experiment objects with their metadata
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    results = encode.search_experiments_by_target(
        target,
        organism=organism,
        assay_title=assay_title,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [_serialize_experiment(exp, encode) for exp in results]


# ============================================================================
# Experiment Tools
# ============================================================================


@server.tool()
def get_experiment(accession: str, api_key: Optional[str] = None) -> dict:
    """
    Get detailed metadata for a specific experiment.
    
    Args:
        accession: ENCODE experiment accession (e.g., 'ENCSR000CDC')
    
    Returns:
        Complete experiment metadata
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)

    return _serialize_experiment(exp, encode)


@server.tool()
def get_all_metadata(accession: str, api_key: Optional[str] = None) -> dict:
    """
    Get all available metadata for an experiment from the ENCODE API.
    
    Args:
        accession: ENCODE experiment accession
    
    Returns:
        Complete raw metadata from ENCODE API
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_all_metadata()


# ============================================================================
# File Discovery Tools
# ============================================================================


@server.tool()
def get_file_types(accession: str, api_key: Optional[str] = None) -> list[str]:
    """
    Get available file types for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of file types (sorted alphabetically)
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_types()


@server.tool()
def get_files_by_type(
    accession: str,
    after_date: Optional[str] = None,
    file_status: str = "released",
    api_key: Optional[str] = None,
) -> dict:
    """
    Get all files from an experiment organized by file type.
    
    Args:
        accession: Experiment accession
        after_date: Optional date filter (YYYY-MM-DD format)
        file_status: Filter by file status (default: 'released')
    
    Returns:
        Dictionary with file type as key and list of file metadata as values
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_files_by_type(after_date=after_date, file_status=file_status)


@server.tool()
def get_file_accessions_by_type(
    accession: str,
    after_date: Optional[str] = None,
    file_types: Optional[list[str]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get file accessions organized by file type.
    
    Args:
        accession: Experiment accession
        after_date: Optional date filter (YYYY-MM-DD format)
        file_types: Optional list of specific file types to include
    
    Returns:
        Dictionary with file type as key and list of accessions as values
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_type(after_date=after_date, file_types=file_types)


@server.tool()
def get_available_output_categories(accession: str, api_key: Optional[str] = None) -> list[str]:
    """
    Get available output categories for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of output categories (e.g., 'raw data', 'processed data')
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_available_output_categories()


@server.tool()
def get_available_output_types(accession: str, api_key: Optional[str] = None) -> list[str]:
    """
    Get available output types for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of output types (e.g., 'reads', 'alignments', 'peaks')
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_available_output_types()


@server.tool()
def get_file_accessions_by_output_category(
    accession: str,
    output_categories: Optional[list[str]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get file accessions organized by output category.
    
    Args:
        accession: Experiment accession
        output_categories: Optional list of categories to filter by
    
    Returns:
        Dictionary with category as key and list of accessions as values
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_output_category(
        output_categories=output_categories
    )


@server.tool()
def get_file_accessions_by_output_type(
    accession: str,
    output_types: Optional[list[str]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get file accessions organized by output type.
    
    Args:
        accession: Experiment accession
        output_types: Optional list of output types to filter by
    
    Returns:
        Dictionary with output type as key and list of accessions as values
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_output_type(output_types=output_types)


@server.tool()
def get_files_summary(
    accession: str,
    max_files_per_type: Optional[int] = None,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get a summary view of files by type.
    
    Args:
        accession: Experiment accession
        max_files_per_type: Maximum files to show per type
    
    Returns:
        Dictionary with file type summary
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_files_summary(max_files_per_type=max_files_per_type)


# ============================================================================
# File Metadata Tools
# ============================================================================


@server.tool()
def get_file_metadata(
    accession: str,
    file_accession: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get comprehensive metadata for a specific file.
    
    Args:
        accession: Experiment accession
        file_accession: File accession ID
    
    Returns:
        Complete file metadata dictionary
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    metadata = exp.get_file_metadata(file_accession)
    
    if metadata is None:
        return {"error": f"File accession {file_accession} not found"}
    
    return metadata


@server.tool()
def get_file_url(
    accession: str,
    file_accession: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get download URL for a specific file.
    
    Args:
        accession: Experiment accession
        file_accession: File accession ID
    
    Returns:
        Dictionary with download URL or error message
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    url = exp.get_file_url(file_accession)
    
    if url is None:
        return {"error": f"File accession {file_accession} not found"}
    
    return {"url": url}


# ============================================================================
# File Accession Tools (no experiment accession required)
# ============================================================================


@server.tool()
def search_by_file_accession(
    file_accession: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    Find the experiment that contains a given file accession.

    Works for any ENCODE file. If the file belongs to an experiment the full
    experiment metadata is returned. If the file exists but is NOT part of an
    experiment (e.g., a genome reference or annotation), the response says so.

    Args:
        file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

    Returns:
        Dictionary with experiment metadata, or a message when the file is
        not associated with an experiment.
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.search_experiments_by_file_accession(file_accession)

    if exp is None:
        return {
            "experiment": None,
            "file_accession": file_accession,
            "message": (
                "File exists but is not part of an experiment "
                "(e.g., genome reference or annotation)."
            ),
        }

    return _serialize_experiment(exp, encode)


@server.tool()
def search_batch(
    queries: list[dict[str, Any]],
    api_key: Optional[str] = None,
) -> dict:
    """Run multiple search queries in one MCP call."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    raw_results = encode.search_experiments_batch(queries, return_objects=False)

    return {
        key: [_serialize_experiment(experiment, encode) for experiment in experiments]
        for key, experiments in raw_results.items()
    }


@server.tool()
def get_experiment_facets(
    fields: Optional[list[str]] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Return facet counts for common experiment fields."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    return encode.get_experiment_facets(fields=fields)


@server.tool()
def rebuild_search_index(api_key: Optional[str] = None) -> dict:
    """Build or rebuild the optional in-memory search index."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    encode.build_search_index()
    return {
        "message": "Search index rebuilt",
        "stats": encode.get_search_index_stats(),
    }


@server.tool()
def get_search_index_stats(api_key: Optional[str] = None) -> dict:
    """Return statistics about the optional search index."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    return encode.get_search_index_stats()


@server.tool()
def get_performance_stats(api_key: Optional[str] = None) -> dict:
    """Return performance metrics collected by the ENCODE instance."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    return encode.get_performance_stats()


@server.tool()
def export_experiments(
    filepath: str,
    format: str = "json",
    search_mode: Optional[str] = None,
    search_value: Optional[str] = None,
    organism: Optional[str] = None,
    assay_title: Optional[str] = None,
    target: Optional[str] = None,
    exclude_revoked: bool = True,
    api_key: Optional[str] = None,
) -> dict:
    """Export all experiments or a filtered search result to a local file."""
    _check_api_key(api_key)
    encode = get_encode_instance()

    experiments: Optional[list[dict[str, Any]]] = None
    if search_mode and search_value:
        search_results = _run_search(
            encode,
            mode=search_mode,
            value=search_value,
            organism=organism,
            assay_title=assay_title,
            target=target,
            exclude_revoked=exclude_revoked,
            return_objects=False,
        )
        experiments = list(search_results)

    output_path = encode.export_experiments(filepath, experiments=experiments, format=format)
    return {
        "path": str(output_path),
        "format": format,
        "exported": len(experiments) if experiments is not None else len(encode.get_experiment_summaries()),
    }


@server.tool()
def get_file_metadata_by_accession(
    file_accession: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get comprehensive metadata for any ENCODE file by its accession alone.

    Works for ALL files — experiment files, genome references, annotations,
    etc. No experiment accession is required.

    Args:
        file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

    Returns:
        Complete file metadata dictionary, or error message.
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    metadata = encode.get_file_metadata(file_accession)

    if metadata is None:
        return {"error": f"File accession {file_accession} not found"}

    return metadata


@server.tool()
def get_file_metadata_batch_by_accession(
    file_accessions: list[str],
    api_key: Optional[str] = None,
) -> dict:
    """Get metadata for multiple file accessions in one call."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    return encode.get_file_metadata_batch(file_accessions)


@server.tool()
def get_file_url_by_accession(
    file_accession: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    Get the download URL for any ENCODE file by its accession alone.

    Works for ALL files — experiment files, genome references, annotations,
    etc. No experiment accession is required.

    Args:
        file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

    Returns:
        Dictionary with download URL, or error message.
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    url = encode.get_file_url(file_accession)

    if url is None:
        return {"error": f"File accession {file_accession} not found"}

    return {"url": url}


@server.tool()
def get_file_url_batch_by_accession(
    file_accessions: list[str],
    api_key: Optional[str] = None,
) -> dict:
    """Get download URLs for multiple file accessions in one call."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    return encode.get_file_url_batch(file_accessions)


@server.tool()
def search_by_file_accession_batch(
    file_accessions: list[str],
    api_key: Optional[str] = None,
) -> dict:
    """Resolve multiple file accessions to experiment metadata when available."""
    _check_api_key(api_key)
    encode = get_encode_instance()
    results = encode.search_experiments_by_file_accessions(file_accessions, return_objects=False)
    return {
        accession: (_serialize_experiment(experiment, encode) if experiment else None)
        for accession, experiment in results.items()
    }


# ============================================================================
# Download Tools
# ============================================================================


@server.tool()
def download_files(
    accession: str,
    file_types: Optional[list[str]] = None,
    file_accessions: Optional[list[str]] = None,
    resume: bool = False,
    verify_checksum: bool = False,
    preview_only: bool = False,
    api_key: Optional[str] = None,
) -> dict:
    """
    Download files from an experiment.
    
    Files are saved to: ./files/{accession}/
    
    Args:
        accession: Experiment accession
        file_types: Optional list of file types to download
        file_accessions: Optional list of specific file accessions to download
    
    Returns:
        Dictionary with download results (downloaded, failed, skipped lists)
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    
    result = exp.download_files(
        str(FILES_DIR / accession),
        file_types=file_types,
        accessions=file_accessions,
        resume=resume,
        verify_checksum=verify_checksum,
        preview_only=preview_only,
    )
    
    return {
        "downloaded": result["downloaded"],
        "failed": result["failed"],
        "skipped": result["skipped"],
        "output_dir": result["output_dir"],
        "manifest": result.get("manifest", []),
    }


# ============================================================================
# Cache Management Tools
# ============================================================================


@server.tool()
def get_cache_stats(api_key: Optional[str] = None) -> dict:
    """
    Get statistics about the metadata cache.
    
    Returns:
        Dictionary with cache statistics
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    stats = encode.get_metadata_cache_stats()
    
    return {
        "cache_dir": stats["cache_dir"],
        "total_cached_experiments": stats["total_cached_experiments"],
        "cache_size_mb": stats["cache_size_mb"],
        "type_prefixes": stats["type_prefixes"],
        "summary_cache_file": str(encode.summary_cache_file),
        "summary_cache_exists": encode.summary_cache_file.exists(),
    }


@server.tool()
def clear_cache(clear_metadata: bool = False, api_key: Optional[str] = None) -> dict:
    """
    Clear caches.
    
    Args:
        clear_metadata: If True, also clear metadata cache
    
    Returns:
        Confirmation message
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    
    if clear_metadata:
        encode.clear_cache()
        encode.clear_metadata_cache()
        _reset_encode_instance()
        return {"message": "Main experiments cache and metadata cache cleared"}
    else:
        encode.clear_cache()
        _reset_encode_instance()
        return {"message": "Main experiments cache cleared"}


# ============================================================================
# Utility Tools
# ============================================================================


@server.tool()
def list_experiments(
    limit: int = 100,
    offset: int = 0,
    api_key: Optional[str] = None,
) -> dict:
    """
    List loaded experiments with pagination.
    
    Args:
        limit: Maximum number of experiments to return
        offset: Starting index
    
    Returns:
        Dictionary with experiment list and pagination info
    """
    _check_api_key(api_key)
    encode = get_encode_instance()
    experiments_source = encode.get_experiment_summaries()
    total = len(experiments_source)
    experiments = experiments_source[offset : offset + limit]
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(experiments),
        "experiments": [
            {
                "accession": exp.get("accession"),
                "assay_title": exp.get("assay_title"),
                "biosample_summary": exp.get("biosample_summary"),
                "organism": encode.get_organism_from_experiment(exp),
                "status": exp.get("status"),
            }
            for exp in experiments
        ],
    }


@server.tool()
def get_server_info(api_key: Optional[str] = None) -> dict:
    """
    Get server configuration information.
    
    Returns:
        Dictionary with server settings
    """
    _check_api_key(api_key)
    return {
        "server_name": "ENCODE fastmcp Server",
        "version": __version__,
        "work_dir": str(WORK_DIR),
        "cache_dir": str(CACHE_DIR),
        "files_dir": str(FILES_DIR),
        "auth_required": _REQUIRE_API_KEY,
        "load_mode": _SERVER_LOAD_MODE,
        "incremental_batch_size": _SERVER_INCREMENTAL_BATCH_SIZE,
        "build_index_enabled": _SERVER_BUILD_INDEX,
        "metrics_enabled": _SERVER_ENABLE_METRICS,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ENCODE fastmcp Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument(
        "--load-mode",
        choices=["eager", "lazy", "incremental"],
        default=_SERVER_LOAD_MODE,
        help="Experiment loading mode for the shared ENCODE instance",
    )
    parser.add_argument(
        "--incremental-batch-size",
        type=int,
        default=_SERVER_INCREMENTAL_BATCH_SIZE,
        help="Default batch size when the server runs in incremental mode",
    )
    parser.add_argument(
        "--build-search-index",
        action="store_true",
        default=_SERVER_BUILD_INDEX,
        help="Build the optional in-memory search index on server startup",
    )
    parser.add_argument(
        "--enable-metrics",
        action="store_true",
        default=_SERVER_ENABLE_METRICS,
        help="Enable lightweight ENCODE request metrics collection",
    )
    parser.add_argument(
        "--require-api-key",
        action="store_true",
        default=False,
        help="Require ENCODE_SERVER_API_KEY env var for tool access",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.require_api_key:
        _REQUIRE_API_KEY = True  # noqa: F841 – module-level override

    _SERVER_LOAD_MODE = args.load_mode
    _SERVER_INCREMENTAL_BATCH_SIZE = args.incremental_batch_size
    _SERVER_BUILD_INDEX = args.build_search_index
    _SERVER_ENABLE_METRICS = args.enable_metrics

    logger.info("Starting ENCODE fastmcp Server v%s ...", __version__)
    logger.info("Work directory: %s", WORK_DIR)
    logger.info("Cache directory: %s", CACHE_DIR)
    logger.info("Files directory: %s", FILES_DIR)
    logger.info("Auth required: %s", _REQUIRE_API_KEY)
    logger.info("Load mode: %s", _SERVER_LOAD_MODE)
    logger.info("Incremental batch size: %s", _SERVER_INCREMENTAL_BATCH_SIZE)
    logger.info("Build search index: %s", _SERVER_BUILD_INDEX)
    logger.info("Metrics enabled: %s", _SERVER_ENABLE_METRICS)

    # Run the fastmcp server on HTTP
    server.run(transport="http", host=args.host, port=args.port)
