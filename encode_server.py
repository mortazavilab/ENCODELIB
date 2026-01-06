#!/usr/bin/env python3
"""
ENCODE fastmcp Server

A fastmcp server exposing ENCODE library functionality.
Runs on http://0.0.0.0:8080

Usage:
    fastmcp run encode_server.py
"""

import json
import logging
from pathlib import Path
from typing import Optional
from fastmcp import FastMCP

from encodeLib import ENCODE, encodeExperiment

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
        "version": "1.0.0",
        "port": 8080,
        "host": "0.0.0.0",
        "work_dir": str(WORK_DIR),
        "cache_dir": str(CACHE_DIR),
        "files_dir": str(FILES_DIR),
    }


if __name__ == "__main__":
    logger.info("Starting ENCODE fastmcp Server...")
    logger.info(f"Work directory: {WORK_DIR}")
    logger.info(f"Cache directory: {CACHE_DIR}")
    logger.info(f"Files directory: {FILES_DIR}")
    logger.info("Server running on stdio transport for MCP clients")
    
    # Run the fastmcp server on HTTP
    server.run(transport="http", host=".0.0.0", port=8080)
