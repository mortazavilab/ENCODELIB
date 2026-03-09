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
from typing import Optional
from fastmcp import FastMCP

from encodeLib import ENCODE, encodeExperiment


__version__ = "0.3"

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
        _encode_instance = ENCODE(use_cache=True, cache_dir=str(CACHE_DIR))
    return _encode_instance


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
    encode = get_encode_instance()
    results = encode.search_experiments_by_biosample(
        search_term,
        organism=organism,
        assay_title=assay_title,
        target=target,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [
        {
            "accession": exp.accession,
            "organism": exp.organism,
            "assay": exp.assay,
            "biosample": exp.biosample,
            "lab": exp.lab,
            "status": exp.status,
            "targets": exp.targets,
            "replicate_count": exp.replicate_count,
            "description": exp.description,
            "link": exp.link,
        }
        for exp in results
    ]

@server.tool()
def search_by_organism(
    organism: str,
    search_term: Optional[str] = None,
    assay_title: Optional[str] = None,
    target: Optional[str] = None,
    exclude_revoked: bool = True,
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
    encode = get_encode_instance()
    results = encode.search_experiments_by_organism(
        organism,
        search_term=search_term,
        assay_title=assay_title,
        target=target,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [
        {
            "accession": exp.accession,
            "organism": exp.organism,
            "assay": exp.assay,
            "biosample": exp.biosample,
            "lab": exp.lab,
            "status": exp.status,
            "targets": exp.targets,
            "replicate_count": exp.replicate_count,
            "description": exp.description,
            "link": exp.link,
        }
        for exp in results
    ]

@server.tool()
def search_by_target(
    target: str,
    organism: Optional[str] = None,
    assay_title: Optional[str] = None,
    exclude_revoked: bool = True,
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
    encode = get_encode_instance()
    results = encode.search_experiments_by_target(
        target,
        organism=organism,
        assay_title=assay_title,
        exclude_revoked=exclude_revoked,
        return_objects=True,
    )
    
    return [
        {
            "accession": exp.accession,
            "organism": exp.organism,
            "assay": exp.assay,
            "biosample": exp.biosample,
            "lab": exp.lab,
            "status": exp.status,
            "targets": exp.targets,
            "replicate_count": exp.replicate_count,
            "description": exp.description,
            "link": exp.link,
        }
        for exp in results
    ]


# ============================================================================
# Experiment Tools
# ============================================================================


@server.tool()
def get_experiment(accession: str) -> dict:
    """
    Get detailed metadata for a specific experiment.
    
    Args:
        accession: ENCODE experiment accession (e.g., 'ENCSR000CDC')
    
    Returns:
        Complete experiment metadata
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    
    return {
        "accession": exp.accession,
        "organism": exp.organism,
        "assay": exp.assay,
        "biosample": exp.biosample,
        "lab": exp.lab,
        "status": exp.status,
        "targets": exp.targets,
        "replicate_count": exp.replicate_count,
        "description": exp.description,
        "link": exp.link,
    }


@server.tool()
def get_all_metadata(accession: str) -> dict:
    """
    Get all available metadata for an experiment from the ENCODE API.
    
    Args:
        accession: ENCODE experiment accession
    
    Returns:
        Complete raw metadata from ENCODE API
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_all_metadata()


# ============================================================================
# File Discovery Tools
# ============================================================================


@server.tool()
def get_file_types(accession: str) -> list[str]:
    """
    Get available file types for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of file types (sorted alphabetically)
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_types()


@server.tool()
def get_files_by_type(
    accession: str,
    after_date: Optional[str] = None,
    file_status: str = "released",
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
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_files_by_type(after_date=after_date, file_status=file_status)


@server.tool()
def get_file_accessions_by_type(
    accession: str,
    after_date: Optional[str] = None,
    file_types: Optional[list[str]] = None,
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
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_type(after_date=after_date, file_types=file_types)


@server.tool()
def get_available_output_categories(accession: str) -> list[str]:
    """
    Get available output categories for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of output categories (e.g., 'raw data', 'processed data')
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_available_output_categories()


@server.tool()
def get_available_output_types(accession: str) -> list[str]:
    """
    Get available output types for an experiment.
    
    Args:
        accession: Experiment accession
    
    Returns:
        List of output types (e.g., 'reads', 'alignments', 'peaks')
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_available_output_types()


@server.tool()
def get_file_accessions_by_output_category(
    accession: str,
    output_categories: Optional[list[str]] = None,
) -> dict:
    """
    Get file accessions organized by output category.
    
    Args:
        accession: Experiment accession
        output_categories: Optional list of categories to filter by
    
    Returns:
        Dictionary with category as key and list of accessions as values
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_output_category(
        output_categories=output_categories
    )


@server.tool()
def get_file_accessions_by_output_type(
    accession: str,
    output_types: Optional[list[str]] = None,
) -> dict:
    """
    Get file accessions organized by output type.
    
    Args:
        accession: Experiment accession
        output_types: Optional list of output types to filter by
    
    Returns:
        Dictionary with output type as key and list of accessions as values
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_file_accessions_by_output_type(output_types=output_types)


@server.tool()
def get_files_summary(
    accession: str,
    max_files_per_type: Optional[int] = None,
) -> dict:
    """
    Get a summary view of files by type.
    
    Args:
        accession: Experiment accession
        max_files_per_type: Maximum files to show per type
    
    Returns:
        Dictionary with file type summary
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    return exp.get_files_summary(max_files_per_type=max_files_per_type)


# ============================================================================
# File Metadata Tools
# ============================================================================


@server.tool()
def get_file_metadata(accession: str, file_accession: str) -> dict:
    """
    Get comprehensive metadata for a specific file.
    
    Args:
        accession: Experiment accession
        file_accession: File accession ID
    
    Returns:
        Complete file metadata dictionary
    """
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    metadata = exp.get_file_metadata(file_accession)
    
    if metadata is None:
        return {"error": f"File accession {file_accession} not found"}
    
    return metadata


@server.tool()
def get_file_url(accession: str, file_accession: str) -> dict:
    """
    Get download URL for a specific file.
    
    Args:
        accession: Experiment accession
        file_accession: File accession ID
    
    Returns:
        Dictionary with download URL or error message
    """
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
def search_by_file_accession(file_accession: str) -> dict:
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

    return {
        "accession": exp.accession,
        "organism": exp.organism,
        "assay": exp.assay,
        "biosample": exp.biosample,
        "lab": exp.lab,
        "status": exp.status,
        "targets": exp.targets,
        "replicate_count": exp.replicate_count,
        "description": exp.description,
        "link": exp.link,
    }


@server.tool()
def get_file_metadata_by_accession(file_accession: str) -> dict:
    """
    Get comprehensive metadata for any ENCODE file by its accession alone.

    Works for ALL files — experiment files, genome references, annotations,
    etc. No experiment accession is required.

    Args:
        file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

    Returns:
        Complete file metadata dictionary, or error message.
    """
    encode = get_encode_instance()
    metadata = encode.get_file_metadata(file_accession)

    if metadata is None:
        return {"error": f"File accession {file_accession} not found"}

    return metadata


@server.tool()
def get_file_url_by_accession(file_accession: str) -> dict:
    """
    Get the download URL for any ENCODE file by its accession alone.

    Works for ALL files — experiment files, genome references, annotations,
    etc. No experiment accession is required.

    Args:
        file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

    Returns:
        Dictionary with download URL, or error message.
    """
    encode = get_encode_instance()
    url = encode.get_file_url(file_accession)

    if url is None:
        return {"error": f"File accession {file_accession} not found"}

    return {"url": url}


# ============================================================================
# Download Tools
# ============================================================================


@server.tool()
def download_files(
    accession: str,
    file_types: Optional[list[str]] = None,
    file_accessions: Optional[list[str]] = None,
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
    encode = get_encode_instance()
    exp = encode.getExperiment(accession)
    
    result = exp.download_files(
        str(FILES_DIR / accession),
        file_types=file_types,
        accessions=file_accessions,
    )
    
    return {
        "downloaded": result["downloaded"],
        "failed": result["failed"],
        "skipped": result["skipped"],
        "output_dir": result["output_dir"],
    }


# ============================================================================
# Cache Management Tools
# ============================================================================


@server.tool()
def get_cache_stats() -> dict:
    """
    Get statistics about the metadata cache.
    
    Returns:
        Dictionary with cache statistics
    """
    encode = get_encode_instance()
    stats = encode.get_metadata_cache_stats()
    
    return {
        "cache_dir": stats["cache_dir"],
        "total_cached_experiments": stats["total_cached_experiments"],
        "cache_size_mb": stats["cache_size_mb"],
        "type_prefixes": stats["type_prefixes"],
    }


@server.tool()
def clear_cache(clear_metadata: bool = False) -> dict:
    """
    Clear caches.
    
    Args:
        clear_metadata: If True, also clear metadata cache
    
    Returns:
        Confirmation message
    """
    encode = get_encode_instance()
    
    if clear_metadata:
        encode.clear_metadata_cache()
        return {"message": "All caches cleared"}
    else:
        encode.clear_cache()
        return {"message": "Main experiments cache cleared"}


# ============================================================================
# Utility Tools
# ============================================================================


@server.tool()
def list_experiments(limit: int = 100, offset: int = 0) -> dict:
    """
    List loaded experiments with pagination.
    
    Args:
        limit: Maximum number of experiments to return
        offset: Starting index
    
    Returns:
        Dictionary with experiment list and pagination info
    """
    encode = get_encode_instance()
    total = len(encode.experiments)
    experiments = encode.experiments[offset : offset + limit]
    
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
                "organism": exp.get("organism"),
                "status": exp.get("status"),
            }
            for exp in experiments
        ],
    }


@server.tool()
def get_server_info() -> dict:
    """
    Get server configuration information.
    
    Returns:
        Dictionary with server settings
    """
    return {
        "server_name": "ENCODE fastmcp Server",
        "version": __version__,
        "work_dir": str(WORK_DIR),
        "cache_dir": str(CACHE_DIR),
        "files_dir": str(FILES_DIR),
        "auth_required": _REQUIRE_API_KEY,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ENCODE fastmcp Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
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

    logger.info("Starting ENCODE fastmcp Server v%s ...", __version__)
    logger.info("Work directory: %s", WORK_DIR)
    logger.info("Cache directory: %s", CACHE_DIR)
    logger.info("Files directory: %s", FILES_DIR)
    logger.info("Auth required: %s", _REQUIRE_API_KEY)

    # Run the fastmcp server on HTTP
    server.run(transport="http", host=args.host, port=args.port)
