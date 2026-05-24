from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests


__version__ = "0.4"

logger = logging.getLogger(__name__)


class ENCODEError(Exception):
    """Base exception for ENCODELIB errors."""


class ENCODEAPIError(ENCODEError):
    """Raised when the ENCODE API returns an unexpected or unusable response."""


class ENCODEValidationError(ENCODEError):
    """Raised when ENCODE data or caller input fails validation."""


class ENCODEDownloadError(ENCODEError):
    """Raised when file download verification fails."""


_METRICS_ENABLED = False
_GLOBAL_METRICS: dict[str, float | int] = {
    "http_requests": 0,
    "http_retries": 0,
    "http_failures": 0,
    "http_latency_seconds": 0.0,
}


def _set_metrics_enabled(enabled: bool) -> None:
    """Enable or disable lightweight global request metrics collection."""
    global _METRICS_ENABLED
    _METRICS_ENABLED = enabled


def _record_metric(name: str, value: int | float = 1) -> None:
    """Record a metric when collection is enabled."""
    if not _METRICS_ENABLED:
        return
    _GLOBAL_METRICS[name] = _GLOBAL_METRICS.get(name, 0) + value

# ---------------------------------------------------------------------------
# HTTP helper with retry + exponential backoff
# ---------------------------------------------------------------------------

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 1  # seconds

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _request_with_retry(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    timeout: int = 30,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    stream: bool = False,
    headers: Optional[dict[str, str]] = None,
) -> requests.Response:
    """HTTP GET with exponential-backoff retry on transient failures.

    Retries on ``ConnectionError``, ``Timeout``, and HTTP 429 / 5xx.
    Client errors (4xx other than 429) are **not** retried.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        started_at = time.perf_counter()
        try:
            _record_metric("http_requests")
            response = requests.get(
                url,
                params=params,
                timeout=timeout,
                stream=stream,
                headers=headers,
            )
            _record_metric("http_latency_seconds", time.perf_counter() - started_at)
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < max_retries:
                wait = _DEFAULT_BACKOFF_BASE * (2 ** (attempt - 1))
                _record_metric("http_retries")
                logger.warning(
                    "Retryable HTTP %s from %s – retry %d/%d in %.1fs",
                    response.status_code, url, attempt, max_retries, wait,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            _record_metric("http_latency_seconds", time.perf_counter() - started_at)
            if attempt < max_retries:
                wait = _DEFAULT_BACKOFF_BASE * (2 ** (attempt - 1))
                _record_metric("http_retries")
                logger.warning(
                    "%s for %s – retry %d/%d in %.1fs",
                    type(exc).__name__, url, attempt, max_retries, wait,
                )
                time.sleep(wait)
            else:
                _record_metric("http_failures")
                raise
        except requests.exceptions.HTTPError:
            _record_metric("http_latency_seconds", time.perf_counter() - started_at)
            _record_metric("http_failures")
            raise  # non-retryable HTTP errors bubble immediately
    # Should not be reached, but satisfy type checkers
    raise last_exc  # type: ignore[misc]


class encodeExperiment:
    """Represents a single ENCODE experiment with its metadata."""
    
    def __init__(
        self,
        accession: Optional[str] = None,
        encode_obj: Optional[Any] = None,
        experiment_data: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Initialize an encodeExperiment object.
        
        Parameters:
        - accession: ENCODE experiment accession (e.g., 'ENCSR000CDC')
        - encode_obj: ENCODE object for accessing helper methods (optional)
        - experiment_data: Full experiment dict from ENCODE API (optional). If provided, no API call needed.
        
        Can be initialized in two ways:
        1. With accession only: encodeExperiment('ENCSR000CDC', encode_obj)
        2. With full data: encodeExperiment(experiment_data=exp_dict, encode_obj=encode_obj)
        """
        self.accession = accession
        self.encode_obj = encode_obj
        self.experiment_data = experiment_data
        
        # Initialize all attributes
        self.organism = None
        self.assay = None
        self.biosample = None
        self.lab = None
        self.status = None
        self.link = None
        self.targets = []
        self.description = None
        self.replicate_count = 0
        
        # Cache for files_by_type to avoid redundant parsing
        self._files_by_type_cache = None
        
        # Load and extract metadata
        self._load_data()
        if self.experiment_data:
            self._extract_metadata()
    
    def _load_data(self) -> None:
        """Load experiment data if not already provided."""
        if self.experiment_data:
            # Data already provided in constructor
            if not self.accession and 'accession' in self.experiment_data:
                self.accession = self.experiment_data.get('accession')
            return
        
        if not self.accession:
            raise ValueError("Must provide either accession or experiment_data")
        
        # Try to load from metadata cache first (if encode_obj is available)
        if self.encode_obj:
            cached_data = self.encode_obj._load_experiment_metadata(self.accession)
            if cached_data:
                self.experiment_data = cached_data
                return
        
        # Try to get from encode_obj's experiments list
        if self.encode_obj:
            for exp in self.encode_obj.get_loaded_experiments():
                if exp.get('accession') == self.accession:
                    self.experiment_data = exp
                    # Cache this data
                    self.encode_obj._save_experiment_metadata(self.accession, exp)
                    return
        
        # Fetch from API if not found in loaded experiments
        url = f"https://www.encodeproject.org/experiments/{self.accession}/"
        try:
            response = _request_with_retry(url, params={"format": "json"}, timeout=30)
            self.experiment_data = response.json()
            # Cache the fetched data
            if self.encode_obj:
                self.encode_obj._save_experiment_metadata(self.accession, self.experiment_data)
        except Exception as e:
            raise ValueError(f"Could not load experiment {self.accession}: {e}")
    
    def _fetch_full_data(self) -> bool:
        """
        Fetch full experiment data from ENCODE API to ensure files are included.
        This is necessary because the cached experiments list may not include the files array.
        Uses frame=embedded to get nested objects like files.
        """
        if not self.accession:
            raise ValueError("Must have accession to fetch data")
        
        url = f"https://www.encodeproject.org/experiments/{self.accession}/"
        try:
            # Use frame=embedded to get nested objects like files
            response = _request_with_retry(url, params={"format": "json", "frame": "embedded"}, timeout=30)
            self.experiment_data = response.json()
            # Clear the files cache since we have new data
            self._files_by_type_cache = None
            # Cache the full data
            if self.encode_obj:
                self.encode_obj._save_experiment_metadata(self.accession, self.experiment_data)
            return True
        except Exception as e:
            raise ValueError(f"Could not fetch experiment {self.accession}: {e}")
    
    def _ensure_full_data(self) -> None:
        """
        Ensure we have full experiment data including files with embedded objects.
        Fetches from API if files are not present or not fully embedded in current data.
        """
        needs_fetch = False
        
        # Check if we have experiment data
        if not self.experiment_data:
            needs_fetch = True
        else:
            # Check if files are present and have the expected structure
            files = self.experiment_data.get('files', [])
            if not files:
                needs_fetch = True
            elif isinstance(files, list) and len(files) > 0:
                # Check if files are fully embedded (have 'accession' field)
                # vs just URL references (strings)
                first_file = files[0]
                if isinstance(first_file, str):
                    # Files are just URL references, need to fetch embedded
                    needs_fetch = True
                elif isinstance(first_file, dict) and 'accession' not in first_file:
                    # Files are dicts but not fully embedded
                    needs_fetch = True
        
        if needs_fetch:
            self._fetch_full_data()
    
    def _extract_metadata(self) -> None:
        """Extract relevant metadata from experiment data."""
        if not self.experiment_data:
            return
        
        # Accession
        self.accession = self.experiment_data.get('accession', self.accession)
        
        # Organism
        if self.encode_obj:
            self.organism = self.encode_obj.get_organism_from_experiment(self.experiment_data)
        else:
            self.organism = self._get_organism()
        
        # Assay type
        self.assay = self.experiment_data.get('assay_title', 'Unknown')
        
        # Biosample
        self.biosample = self.experiment_data.get('biosample_summary', 'Unknown')
        
        # Lab
        self.lab = self.experiment_data.get('lab', {}).get('title', 'Unknown')
        
        # Status
        self.status = self.experiment_data.get('status', 'Unknown')
        
        # Link
        self.link = f"https://www.encodeproject.org/experiments/{self.accession}/"
        
        # Description
        self.description = self.experiment_data.get('description', '')
        
        # Targets
        self.targets = self._get_targets()
        
        # Replicate count
        self.replicate_count = len(self.experiment_data.get('replicates', []))
    
    def _get_organism(self) -> Optional[str]:
        """Extract organism if encode_obj not available"""
        if 'replicates' not in self.experiment_data or not self.experiment_data['replicates']:
            return None
        
        for replicate in self.experiment_data['replicates']:
            if 'library' in replicate and replicate['library']:
                lib = replicate['library']
                if 'biosample' in lib and lib['biosample']:
                    biosample = lib['biosample']
                    if 'organism' in biosample and biosample['organism']:
                        return biosample['organism'].get('scientific_name')
        return None
    
    def _get_targets(self) -> list[str]:
        """Extract target(s) from experiment data"""
        target_field = self.experiment_data.get('target', None)
        
        if not target_field:
            return []
        
        # Handle single target (dict)
        if isinstance(target_field, dict):
            label = target_field.get('label', '')
            return [label] if label else []
        
        # Handle multiple targets (list)
        if isinstance(target_field, list):
            labels = []
            for target in target_field:
                if isinstance(target, dict):
                    label = target.get('label', '')
                    if label:
                        labels.append(label)
                elif isinstance(target, str):
                    labels.append(target)
            return labels
        
        # Handle string target
        if isinstance(target_field, str):
            return [target_field]
        
        return []
    
    def __str__(self) -> str:
        """Return a formatted string representation of the experiment"""
        target_str = ', '.join(self.targets) if self.targets else 'None'
        lines = [
            "=" * 80,
            f"ENCODE Experiment: {self.accession}",
            "=" * 80,
            f"Organism:        {self.organism or 'N/A'}",
            f"Assay:           {self.assay}",
            f"Target:          {target_str}",
            f"Biosample:       {self.biosample}",
            f"Lab:             {self.lab}",
            f"Status:          {self.status}",
            f"Replicates:      {self.replicate_count}",
            f"Description:     {self.description[:70] + '...' if len(self.description) > 70 else self.description}",
            f"Link:            {self.link}",
            "=" * 80
        ]
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        """Return a developer-friendly representation"""
        return f"encodeExperiment(accession='{self.accession}')"
    
    def to_dict(self) -> dict[str, Any]:
        """Return metadata as a dictionary"""
        return {
            'Accession': self.accession,
            'Organism': self.organism,
            'Assay': self.assay,
            'Targets': self.targets,
            'Biosample': self.biosample,
            'Lab': self.lab,
            'Status': self.status,
            'Replicates': self.replicate_count,
            'Description': self.description,
            'Link': self.link
        }
    
    def get_all_metadata(self) -> dict[str, Any]:
        """
        Get all available metadata for this experiment from the ENCODE API.
        
        Returns:
        - Dictionary with all experiment metadata including:
          - Basic metadata (accession, status, organism, etc.)
          - Derived metadata (dates, assembly info, etc.)
          - References (files, replicates, controls, etc.)
          - Full raw data from the ENCODE API
        """
        if not self.experiment_data:
            return {}
        
        return self.experiment_data
    
    def get_files_by_type(self, after_date: Optional[str] = None, file_status: str = 'released') -> dict[str, list[dict[str, Any]]]:
        """
        Get all files from this experiment organized by file type with comprehensive metadata.
        
        Parameters:
        - after_date: Optional date string (YYYY-MM-DD) to filter processed files released after this date
        - file_status: Filter files by status (default: 'released')
        
        Returns:
        - Dictionary with structure:
          {
            'file_type1': [
              {
                'accession': 'ENCFF...',
                'filename': '...',
                'title': '...',
                'date_released': '...',
                'output_type': '...',
                'output_category': '...',
                'file_size': int,
                'file_format': '...',
                'status': '...',
                'preferred_default': bool,
                'biological_replicates': list,
                'technical_replicates': list,
                'mapped_read_length': int or None,
                'read_length_units': '...',
                'assembly': '...',
                'genome_annotation': '...',
                'derived_from': list,
                'target': '...',
                'md5sum': '...',
                'content_md5sum': '...',
                and all other available fields from the ENCODE API
              },
              ...
            ],
            'file_type2': [...],
            ...
          }
        """
        # Return cached result if available and no filters applied
        cache_key = (after_date, file_status)
        if self._files_by_type_cache is not None and self._files_by_type_cache[0] == cache_key:
            return self._files_by_type_cache[1]
        
        # Ensure we have full experiment data with files
        self._ensure_full_data()
        
        files_by_type = {}
        
        # Get files from experiment data
        files = self.experiment_data.get('files', []) if self.experiment_data else []
        
        # Parse after_date if provided
        after_datetime = None
        if after_date:
            try:
                after_datetime = datetime.strptime(after_date, '%Y-%m-%d')
            except ValueError:
                raise ValueError(f"Invalid date format: {after_date}. Use YYYY-MM-DD")
        
        # Define commonly used fields to include first (in preferred order)
        priority_fields = [
            'accession', 'filename', 'title', 'date_released', 'output_type', 
            'output_category', 'file_size', 'file_format', 'status', 'preferred_default',
            'biological_replicates', 'biological_replicates_formatted', 'technical_replicates',
            'mapped_read_length', 'mapped_run_type', 'read_length_units', 'assembly',
            'genome_annotation', 'derived_from', 'target', 'md5sum', 'content_md5sum',
            'submitted_file_name', 'uuid'
        ]
        
        for file_obj in files:
            # Filter by file status
            if file_obj.get('status', '') != file_status:
                continue
            
            # Filter by date if specified
            if after_datetime:
                date_released = file_obj.get('date_released')
                if date_released:
                    try:
                        release_dt = datetime.strptime(date_released[:10], '%Y-%m-%d')
                        if release_dt < after_datetime:
                            continue
                    except (ValueError, TypeError):
                        pass
            
            # Get file type
            file_type = file_obj.get('file_type', 'unknown')
            
            # Build comprehensive file metadata dictionary
            file_metadata = {}
            
            # First add priority fields that are likely to exist
            for field in priority_fields:
                if field in file_obj:
                    file_metadata[field] = file_obj[field]
            
            # Add any other fields not in priority_fields (skip @-prefixed internal fields)
            for key, value in file_obj.items():
                if key not in file_metadata and not key.startswith('@'):
                    file_metadata[key] = value
            
            # Add to dictionary
            if file_type not in files_by_type:
                files_by_type[file_type] = []
            
            files_by_type[file_type].append(file_metadata)
        
        # Cache the result
        self._files_by_type_cache = (cache_key, files_by_type)
        
        return files_by_type
    
    def get_file_accessions_by_type(self, after_date: Optional[str] = None, file_types: Optional[list[str]] = None) -> dict[str, list[str]]:
        """
        Get a simplified dictionary of file accessions organized by file type.
        
        Parameters:
        - after_date: Optional date string (YYYY-MM-DD) to filter by release date
        - file_types: Optional list of file types to include (e.g., ['bam', 'bigWig']). 
                      If None, returns all file types.
        
        Returns:
        - Dictionary with file type as key and list of file accessions as values
          {
            'file_type1': ['ENCFF...', 'ENCFF...', ...],
            'file_type2': [...],
            ...
          }
        """
        files_dict = self.get_files_by_type(after_date=after_date)
        accessions_dict = {}
        
        for file_type, files in files_dict.items():
            # Skip file types not in the filter list if file_types is specified
            if file_types is not None and file_type not in file_types:
                continue
            
            accessions_dict[file_type] = [f['accession'] for f in files]
        
        return accessions_dict
    
    def get_file_types(self) -> list[str]:
        """
        Get the list of available file types in this experiment.
        
        Returns:
        - List of file types (e.g., ['bam', 'bigWig', 'bed narrowPeak', 'fastq'])
          sorted alphabetically
        """
        files_by_type = self.get_files_by_type()
        return sorted(files_by_type.keys())
    
    def get_available_output_categories(self) -> list[str]:
        """
        Get the list of available output categories in this experiment.
        
        Returns:
        - List of output categories (e.g., ['raw data', 'processed data'])
          sorted alphabetically
        """
        files_by_type = self.get_files_by_type()
        categories = set()
        for files in files_by_type.values():
            for file_obj in files:
                category = file_obj.get('output_category')
                if category:
                    categories.add(category)
        return sorted(categories)
    
    def get_available_output_types(self) -> list[str]:
        """
        Get the list of available output types in this experiment.
        
        Returns:
        - List of output types (e.g., ['reads', 'alignments', 'peaks', 'signal'])
          sorted alphabetically
        """
        files_by_type = self.get_files_by_type()
        types = set()
        for files in files_by_type.values():
            for file_obj in files:
                output_type = file_obj.get('output_type')
                if output_type:
                    types.add(output_type)
        return sorted(types)
    
    def get_file_accessions_by_output_category(self, output_categories: Optional[list[str]] = None) -> dict[str, list[str]]:
        """
        Get file accessions organized by output category (e.g., 'raw data', 'processed data').
        
        Parameters:
        - output_categories: Optional list of output categories to include 
                            (e.g., ['raw data', 'processed data']). 
                            If None, returns all categories.
        
        Returns:
        - Dictionary with output category as key and list of file accessions as values
          {
            'raw data': ['ENCFF...', 'ENCFF...', ...],
            'processed data': [...],
            ...
          }
        """
        files_by_type = self.get_files_by_type()
        accessions_by_category = {}
        
        for files in files_by_type.values():
            for file_obj in files:
                category = file_obj.get('output_category', 'unknown')
                
                # Skip categories not in the filter list if specified
                if output_categories is not None and category not in output_categories:
                    continue
                
                if category not in accessions_by_category:
                    accessions_by_category[category] = []
                
                accession = file_obj.get('accession')
                if accession and accession not in accessions_by_category[category]:
                    accessions_by_category[category].append(accession)
        
        return accessions_by_category
    
    def get_file_accessions_by_output_type(self, output_types: Optional[list[str]] = None) -> dict[str, list[str]]:
        """
        Get file accessions organized by output type (e.g., 'reads', 'alignments', 'peaks').
        
        Parameters:
        - output_types: Optional list of output types to include 
                       (e.g., ['reads', 'alignments']). 
                       If None, returns all output types.
        
        Returns:
        - Dictionary with output type as key and list of file accessions as values
          {
            'reads': ['ENCFF...', 'ENCFF...', ...],
            'alignments': [...],
            ...
          }
        """
        files_by_type = self.get_files_by_type()
        accessions_by_type = {}
        
        for files in files_by_type.values():
            for file_obj in files:
                output_type = file_obj.get('output_type', 'unknown')
                
                # Skip output types not in the filter list if specified
                if output_types is not None and output_type not in output_types:
                    continue
                
                if output_type not in accessions_by_type:
                    accessions_by_type[output_type] = []
                
                accession = file_obj.get('accession')
                if accession and accession not in accessions_by_type[output_type]:
                    accessions_by_type[output_type].append(accession)
        
        return accessions_by_type
    
    def get_file_metadata(self, accession: str) -> Optional[dict[str, Any]]:
        """
        Get comprehensive metadata for a specific file accession.
        
        Parameters:
        - accession: File accession ID (e.g., 'ENCFF001JZK')
        
        Returns:
        - Dictionary with all metadata for the file, or None if not found
        """
        files_by_type = self.get_files_by_type()
        
        for files in files_by_type.values():
            for file_obj in files:
                if file_obj.get('accession') == accession:
                    return file_obj
        
        return None
    
    def get_file_url(self, accession: str) -> Optional[str]:
        """
        Get the download URL for a file accession.
        
        Parameters:
        - accession: File accession ID (e.g., 'ENCFF001JZK')
        
        Returns:
        - URL string for downloading the file (e.g., '/files/ENCFF001JZK/@@download/...')
          or None if not found
        """
        file_metadata = self.get_file_metadata(accession)
        
        if file_metadata:
            # href contains the relative download path
            href = file_metadata.get('href')
            if href:
                # Construct full URL
                return f"https://www.encodeproject.org{href}"
        
        return None
    
    def get_files_summary(self, max_files_per_type: Optional[int] = None) -> dict[str, dict[str, Any]]:
        """
        Get a summary of files organized by type with optional detail limiting.
        
        Parameters:
        - max_files_per_type: Maximum number of files to include per type in output (default: None = all files)
        
        Returns:
        - Dictionary with format:
          {
            'file_type1': {
              'count': 10,
              'files': [file1, file2, ...] (all files if max_files_per_type is None)
            },
            ...
          }
        """
        files_by_type = self.get_files_by_type()
        summary = {}
        
        for file_type, files in files_by_type.items():
            summary[file_type] = {
                'count': len(files),
                'files': files if max_files_per_type is None else files[:max_files_per_type]
            }
        
        return summary
    
    def clear_cache(self, refresh: bool = False) -> bool:
        """
        Clear or refresh the cached metadata for this experiment.
        
        Parameters:
        - refresh: If True, fetch fresh data from API and update cache.
                   If False, just clear cached data.
        
        Returns:
        - True if successful
        """
        if self.encode_obj:
            self.encode_obj.clear_metadata_cache(self.accession)
        
        if refresh:
            self._fetch_full_data()
        else:
            self.experiment_data = None
        
        return True

    def _calculate_md5(self, file_path: Path) -> str:
        """Calculate the MD5 digest for a local file."""
        digest = hashlib.md5()
        with open(file_path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(8192), b''):
                if chunk:
                    digest.update(chunk)
        return digest.hexdigest()

    def _select_files_to_download(
        self,
        file_types: Optional[str | list[str]] = None,
        accessions: Optional[str | list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Return the file objects selected for a download or manifest request."""
        files_by_type = self.get_files_by_type()

        if file_types is not None and isinstance(file_types, str):
            file_types = [file_types]
        if accessions is not None and isinstance(accessions, str):
            accessions = [accessions]

        files_to_download: list[dict[str, Any]] = []
        if accessions:
            for files in files_by_type.values():
                for file_obj in files:
                    if file_obj.get('accession') in accessions:
                        files_to_download.append(file_obj)
        elif file_types:
            for file_type in file_types:
                if file_type in files_by_type:
                    files_to_download.extend(files_by_type[file_type])
        else:
            for files in files_by_type.values():
                files_to_download.extend(files)

        return files_to_download

    def prepare_download_manifest(
        self,
        file_types: Optional[str | list[str]] = None,
        accessions: Optional[str | list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Prepare a manifest for files selected for download."""
        self._ensure_full_data()
        manifest = []
        for file_obj in self._select_files_to_download(file_types=file_types, accessions=accessions):
            href = file_obj.get('href')
            manifest.append(
                {
                    'accession': file_obj.get('accession'),
                    'filename': file_obj.get('filename'),
                    'file_type': file_obj.get('file_type'),
                    'file_format': file_obj.get('file_format'),
                    'file_size': file_obj.get('file_size'),
                    'status': file_obj.get('status'),
                    'output_type': file_obj.get('output_type'),
                    'output_category': file_obj.get('output_category'),
                    'md5sum': file_obj.get('md5sum'),
                    'url': f"https://www.encodeproject.org{href}" if href and not href.startswith('http') else href,
                }
            )
        return manifest
    
    def _download_single_file(
        self,
        file_obj: dict[str, Any],
        output_path: Path,
        *,
        resume: bool = False,
        verify_checksum: bool = False,
    ) -> tuple[str, str, Optional[str]]:
        """Download a single file. Returns (accession, status, error_or_None).

        status is one of: 'downloaded', 'skipped', 'failed'.
        """
        accession = file_obj.get('accession', 'unknown')

        # Resolve filename
        filename = file_obj.get('filename')
        if not filename:
            href = file_obj.get('href', '')
            if href and '@@download/' in href:
                filename = href.split('@@download/')[-1]

        if not accession or not filename:
            return (accession, 'skipped', None)

        # Sanitize filename to prevent path traversal
        filename = os.path.basename(filename)
        if not filename or filename.startswith('.') or '/' in filename or '\\' in filename:
            return (accession, 'failed', "Invalid or unsafe filename")

        file_path = output_path / filename

        expected_md5 = file_obj.get('md5sum') or file_obj.get('content_md5sum')

        # Skip existing files
        if file_path.exists():
            if verify_checksum and expected_md5:
                existing_md5 = self._calculate_md5(file_path)
                if existing_md5 == expected_md5:
                    return (accession, 'skipped', None)
                file_path.unlink()
            else:
                return (accession, 'skipped', None)

        url = file_obj.get('href')
        if not url:
            return (accession, 'failed', "No download URL (href) found")
        if not url.startswith('http'):
            url = f"https://www.encodeproject.org{url}"

        temp_path = output_path / f"{filename}.tmp"
        try:
            headers = None
            write_mode = 'wb'
            file_size = 0
            if resume and temp_path.exists():
                file_size = temp_path.stat().st_size
                if file_size > 0:
                    headers = {'Range': f'bytes={file_size}-'}
                    write_mode = 'ab'

            response = _request_with_retry(url, timeout=300, stream=True, headers=headers)
            if write_mode == 'ab' and getattr(response, 'status_code', 200) != 206:
                write_mode = 'wb'
                file_size = 0

            with open(temp_path, write_mode) as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        file_size += len(chunk)
            temp_path.rename(file_path)

            if verify_checksum and expected_md5:
                actual_md5 = self._calculate_md5(file_path)
                if actual_md5 != expected_md5:
                    file_path.unlink(missing_ok=True)
                    raise ENCODEDownloadError(
                        f"Checksum mismatch for {accession}: expected {expected_md5}, got {actual_md5}"
                    )

            logger.info("Downloaded %s (%s, %s bytes)", accession, filename, f"{file_size:,}")
            return (accession, 'downloaded', None)
        except Exception as exc:
            if temp_path.exists():
                temp_path.unlink()
            return (accession, 'failed', str(exc))

    def download_files(
        self,
        output_dir: str,
        file_types: Optional[str | list[str]] = None,
        accessions: Optional[str | list[str]] = None,
        max_workers: int = 4,
        resume: bool = False,
        verify_checksum: bool = False,
        preview_only: bool = False,
    ) -> dict[str, Any]:
        """
        Download files from this experiment to a local directory.
        
        Automatically ensures experiment metadata is loaded before attempting downloads.
        Uses parallel downloads for speed (configurable via *max_workers*).
        
        Parameters:
        - output_dir: Path to directory where files will be saved (will be created if doesn't exist)
        - file_types: str or list of str specifying file types to download (e.g., 'fastq', ['bam', 'bigWig'])
                      If None and accessions is None, all files are downloaded
        - accessions: str or list of str specifying specific file accessions to download (e.g., 'ENCFF001JZK')
                      Takes precedence over file_types if both specified
        - max_workers: Maximum number of parallel downloads (default: 4)
        - resume: Resume partial downloads from `.tmp` files when the server supports range requests.
        - verify_checksum: Verify the downloaded file MD5 against ENCODE metadata when available.
        - preview_only: Return a manifest of matching files without downloading them.
        
        Returns:
        - Dictionary with download results:
          {
            'downloaded': [list of successfully downloaded file accessions],
            'failed': [list of (accession, error_message) tuples],
            'skipped': [list of file accessions that were skipped],
            'output_dir': Path to output directory
          }
        
        Examples:
        ```python
        # Download all fastq files
        result = exp.download_files('/path/to/output', file_types='fastq')
        
        # Download multiple file types
        result = exp.download_files('/path/to/output', file_types=['fastq', 'bam'])
        
        # Download specific files by accession
        result = exp.download_files('/path/to/output', accessions=['ENCFF001JZK', 'ENCFF002ABC'])
        
        # Download a single file
        result = exp.download_files('/path/to/output', accessions='ENCFF001JZK')
        ```
        """
        # Ensure we have full experiment data with files
        self._ensure_full_data()
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        files_to_download = self._select_files_to_download(file_types=file_types, accessions=accessions)

        if preview_only:
            return {
                'downloaded': [],
                'failed': [],
                'skipped': [],
                'output_dir': str(output_path),
                'manifest': self.prepare_download_manifest(file_types=file_types, accessions=accessions),
            }
        
        downloaded: list[str] = []
        failed: list[tuple[str, str]] = []
        skipped: list[str] = []
        
        print(f"Downloading {len(files_to_download)} file(s) to {output_path}")
        
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    self._download_single_file,
                    fobj,
                    output_path,
                    resume=resume,
                    verify_checksum=verify_checksum,
                ): fobj
                for fobj in files_to_download
            }
            for future in as_completed(futures):
                acc, status, error = future.result()
                if status == 'downloaded':
                    downloaded.append(acc)
                elif status == 'failed':
                    failed.append((acc, error or 'unknown error'))
                else:
                    skipped.append(acc)
        
        # Print summary
        print(f"\nDownload Summary:")
        print(f"  Downloaded: {len(downloaded)}")
        print(f"  Failed: {len(failed)}")
        print(f"  Skipped: {len(skipped)}")
        
        if failed:
            print(f"\nFailed downloads:")
            for acc, error in failed:
                print(f"  {acc}: {error}")
        
        return {
            'downloaded': downloaded,
            'failed': failed,
            'skipped': skipped,
            'output_dir': str(output_path),
            'manifest': self.prepare_download_manifest(file_types=file_types, accessions=accessions),
        }


class ENCODE:
    """ENCODE Portal API interface for querying experiments and retrieving data."""
    
    BASE_URL = "https://www.encodeproject.org"
    CACHE_DIR = Path.home() / ".encode_cache"
    CACHE_FILE = CACHE_DIR / "experiments.json"
    SUMMARY_CACHE_FILE = CACHE_DIR / "experiment_summaries.json"
    METADATA_CACHE_DIR = CACHE_DIR / "metadata"  # Hierarchical cache for individual experiment metadata
    
    def __init__(
        self,
        use_cache: bool = True,
        force_refresh: bool = False,
        cache_dir: Optional[str] = None,
        load_mode: str = "eager",
        incremental_batch_size: int = 250,
        build_index: bool = False,
        enable_metrics: bool = False,
    ) -> None:
        """
        Initialize ENCODE object by loading all experiments from the ENCODE database.
        
        Parameters:
        - use_cache: Use cached experiments if available (default: True)
        - force_refresh: Force downloading from API, ignore cache (default: False)
        - cache_dir: Custom cache directory (default: ~/.encode_cache)
        - load_mode: Loading strategy for the experiments list.
                     'eager' loads at initialization (default).
                     'lazy' defers loading until experiments are accessed.
                     'incremental' keeps lightweight summaries in memory and
                     materializes full experiment data only when explicitly loaded.
        - incremental_batch_size: Default number of experiment summaries to
                                  materialize per batch in incremental mode.
        - build_index: Build the optional search index during initialization.
        - enable_metrics: Enable lightweight request and cache metrics collection.
        """
        if load_mode not in {"eager", "lazy", "incremental"}:
            raise ValueError(f"Unsupported load_mode: {load_mode}")
        if incremental_batch_size < 1:
            raise ValueError("incremental_batch_size must be >= 1")

        self.base_url = self.BASE_URL
        self.url = f"{self.base_url}/experiments/"
        self.query_params: dict[str, str] = {
            "format": "json",
            "limit": "all"  # Get all results
        }
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        self.load_mode = load_mode
        self.incremental_batch_size = incremental_batch_size
        self.enable_metrics = enable_metrics
        if enable_metrics:
            _set_metrics_enabled(True)
        
        # Set cache file location
        if cache_dir:
            self.cache_dir = Path(cache_dir)
            self.cache_file = self.cache_dir / "experiments.json"
            self.summary_cache_file = self.cache_dir / "experiment_summaries.json"
            self.metadata_cache_dir = self.cache_dir / "metadata"
        else:
            self.cache_dir = self.CACHE_DIR
            self.cache_file = self.CACHE_FILE
            self.summary_cache_file = self.SUMMARY_CACHE_FILE
            self.metadata_cache_dir = self.METADATA_CACHE_DIR
        
        # In-memory cache for file-accession lookups (file_accession -> API response)
        self._file_info_cache: dict[str, dict[str, Any]] = {}
        self._experiments: list[dict[str, Any]] = []
        self._experiments_loaded = False
        self._experiment_summaries: list[dict[str, Any]] = []
        self._summary_lookup: dict[str, dict[str, Any]] = {}
        self._search_index: Optional[dict[str, dict[str, set[str]]]] = None
        self._incremental_offset = 0
        self._instance_metrics: dict[str, int] = {
            "summary_cache_hits": 0,
            "summary_cache_misses": 0,
            "metadata_cache_hits": 0,
            "metadata_cache_misses": 0,
            "search_calls": 0,
            "batch_search_calls": 0,
            "exports": 0,
        }

        if self.load_mode == "eager":
            self.load_all_experiments()
        elif self.load_mode == "incremental":
            self.load_experiment_summaries()

        if build_index:
            self.build_search_index()

    @property
    def experiments(self) -> list[dict[str, Any]]:
        """Return the loaded experiments, fetching them first in lazy mode."""
        self._ensure_experiments_loaded()
        return self._experiments

    @experiments.setter
    def experiments(self, value: list[dict[str, Any]]) -> None:
        self._experiments = value
        self._experiments_loaded = True

    def _ensure_experiments_loaded(self) -> None:
        """Load the experiments list on first access when running in lazy mode."""
        if getattr(self, "_experiments_loaded", False):
            return

        if getattr(self, "load_mode", "eager") in {"lazy", "incremental"}:
            self.load_all_experiments()

    def load_all_experiments(self) -> list[dict[str, Any]]:
        """Load and cache the full experiments list, returning the loaded data."""
        self._experiments = self._load_experiments()
        self._experiments_loaded = True
        self._set_experiment_summaries(self._derive_experiment_summaries(self._experiments))
        return self._experiments

    def get_loaded_experiments(self) -> list[dict[str, Any]]:
        """Return only the experiments already loaded in memory.

        Unlike ``experiments``, this never triggers a load. It is used by
        call sites that should avoid forcing eager-style behavior in lazy mode.
        """
        return getattr(self, "_experiments", [])

    def _record_instance_metric(self, name: str, value: int = 1) -> None:
        """Record a per-instance metric."""
        if name not in self._instance_metrics:
            self._instance_metrics[name] = 0
        self._instance_metrics[name] += value

    def _invalidate_search_index(self) -> None:
        """Drop the cached search index so it can be rebuilt from fresh data."""
        self._search_index = None

    def _set_experiment_summaries(self, summaries: list[dict[str, Any]]) -> None:
        """Update in-memory summary state and invalidate dependent caches."""
        self._experiment_summaries = summaries
        self._summary_lookup = {
            exp["accession"]: exp
            for exp in summaries
            if exp.get("accession")
        }
        self._incremental_offset = min(self._incremental_offset, len(self._experiment_summaries))
        self._invalidate_search_index()

    def _derive_experiment_summaries(
        self,
        experiments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Derive lightweight experiment summaries used by lazy/indexed paths."""
        summaries: list[dict[str, Any]] = []
        for experiment in experiments:
            summaries.append(
                {
                    "accession": experiment.get("accession"),
                    "status": experiment.get("status"),
                    "biosample_summary": experiment.get("biosample_summary", ""),
                    "biosample_ontology": experiment.get("biosample_ontology", {}),
                    "assay_title": experiment.get("assay_title", ""),
                    "target": experiment.get("target"),
                    "organism": self.get_organism_from_experiment(experiment),
                    "lab": experiment.get("lab", {}),
                    "description": experiment.get("description", ""),
                    "replicates": experiment.get("replicates", []),
                    "@id": experiment.get("@id", ""),
                }
            )
        return summaries

    def _save_summary_cache(self, summaries: list[dict[str, Any]]) -> None:
        """Persist experiment summaries to the summary cache file."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(self.summary_cache_file, "w") as handle:
                json.dump({"experiments": summaries}, handle)
        except Exception as exc:
            logger.warning("Could not save summary cache (%s)", exc)

    def _load_summary_cache(self) -> Optional[list[dict[str, Any]]]:
        """Load experiment summaries from the summary cache file."""
        if not self.use_cache or not self.summary_cache_file.exists() or self.force_refresh:
            return None

        try:
            with open(self.summary_cache_file, "r") as handle:
                data = json.load(handle)
        except Exception as exc:
            logger.warning("Could not load summary cache (%s)", exc)
            return None

        summaries = data.get("experiments", [])
        if not isinstance(summaries, list):
            raise ENCODEValidationError("Summary cache must contain an 'experiments' list")

        self._record_instance_metric("summary_cache_hits")
        return summaries

    def load_experiment_summaries(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Load experiment summaries without materializing the full experiment list."""
        cached_summaries = None
        if not force_refresh:
            cached_summaries = self._load_summary_cache()

        if cached_summaries is not None:
            self._set_experiment_summaries(cached_summaries)
            return self._experiment_summaries

        self._record_instance_metric("summary_cache_misses")

        if self.use_cache and not force_refresh and self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as handle:
                    data = json.load(handle)
                experiments = data.get("experiments", [])
                if not isinstance(experiments, list):
                    raise ENCODEValidationError("Experiments cache must contain an 'experiments' list")
                summaries = self._derive_experiment_summaries(experiments)
                self._set_experiment_summaries(summaries)
                self._save_summary_cache(summaries)
                return summaries
            except Exception as exc:
                logger.warning("Could not derive summaries from experiments cache (%s)", exc)

        experiments = self._load_experiments()
        summaries = self._derive_experiment_summaries(experiments)
        self._set_experiment_summaries(summaries)
        if self.use_cache:
            self._save_summary_cache(summaries)
        return summaries

    def get_experiment_summaries(self) -> list[dict[str, Any]]:
        """Return experiment summaries without forcing full experiment materialization."""
        if self._experiment_summaries:
            return self._experiment_summaries

        if self._experiments_loaded and self._experiments:
            self._set_experiment_summaries(self._derive_experiment_summaries(self._experiments))
            return self._experiment_summaries

        return self.load_experiment_summaries()

    def load_next_experiment_batch(self, batch_size: Optional[int] = None) -> list[dict[str, Any]]:
        """Materialize the next batch of experiments in incremental mode."""
        summaries = self.get_experiment_summaries()
        if not summaries:
            return []

        batch_size = batch_size or self.incremental_batch_size
        start = self._incremental_offset
        end = min(start + batch_size, len(summaries))
        batch_summaries = summaries[start:end]
        loaded_accessions = {exp.get("accession") for exp in self._experiments}
        batch: list[dict[str, Any]] = []

        for summary in batch_summaries:
            accession = summary.get("accession")
            if not accession:
                continue
            if accession in loaded_accessions:
                continue

            cached_data = self._load_experiment_metadata(accession)
            if cached_data is not None:
                batch.append(cached_data)
                loaded_accessions.add(accession)
                continue

            experiment = self.getExperiment(accession)
            batch.append(experiment.get_all_metadata())
            loaded_accessions.add(accession)

        self._experiments.extend(batch)
        self._incremental_offset = end
        if self._incremental_offset >= len(summaries):
            self._experiments_loaded = True

        return batch

    def _get_search_source(
        self,
        experiments_list: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        """Resolve the dataset used for search without breaking incremental mode."""
        if experiments_list is not None:
            return experiments_list

        if self.load_mode == "incremental" and not self._experiments_loaded:
            return self.get_experiment_summaries()

        return self.experiments

    def build_search_index(self) -> dict[str, dict[str, set[str]]]:
        """Build an optional in-memory search index over experiment summaries."""
        summaries = self.get_experiment_summaries()
        index: dict[str, dict[str, set[str]]] = {
            "biosample_summary": defaultdict(set),
            "biosample_term": defaultdict(set),
            "organism": defaultdict(set),
            "assay_title": defaultdict(set),
            "target": defaultdict(set),
            "status": defaultdict(set),
        }

        for experiment in summaries:
            accession = experiment.get("accession")
            if not accession:
                continue

            biosample_summary = experiment.get("biosample_summary", "")
            if biosample_summary:
                index["biosample_summary"][biosample_summary.lower()].add(accession)

            term_name = experiment.get("biosample_ontology", {}).get("term_name", "")
            if term_name:
                index["biosample_term"][term_name.lower()].add(accession)

            organism = self.get_organism_from_experiment(experiment)
            if organism:
                index["organism"][organism.lower()].add(accession)

            assay_title = experiment.get("assay_title", "")
            if assay_title:
                index["assay_title"][assay_title.lower()].add(accession)

            status = experiment.get("status", "")
            if status:
                index["status"][status.lower()].add(accession)

            for target_name in self.get_targets(experiment):
                if target_name:
                    index["target"][target_name.lower()].add(accession)

        self._search_index = {
            field: {key: set(values) for key, values in values_by_key.items()}
            for field, values_by_key in index.items()
        }
        return self._search_index

    def clear_search_index(self) -> None:
        """Drop the in-memory search index."""
        self._invalidate_search_index()

    def get_search_index_stats(self) -> dict[str, Any]:
        """Return lightweight statistics about the optional search index."""
        if self._search_index is None:
            return {
                "built": False,
                "fields": {},
                "summary_count": len(self.get_experiment_summaries()),
            }

        return {
            "built": True,
            "summary_count": len(self.get_experiment_summaries()),
            "fields": {
                field: {
                    "unique_terms": len(values),
                    "accession_links": sum(len(accessions) for accessions in values.values()),
                }
                for field, values in self._search_index.items()
            },
        }

    def _search_index_matches(
        self,
        field: str,
        search_value: str,
        *,
        exact: bool = False,
    ) -> set[str]:
        """Resolve accessions from the optional index using exact or substring matching."""
        if self._search_index is None:
            return set()

        values = self._search_index.get(field, {})
        lowered = search_value.lower()
        if exact:
            return set(values.get(lowered, set()))

        matches: set[str] = set()
        for candidate, accessions in values.items():
            if lowered in candidate:
                matches.update(accessions)
        return matches

    def _get_indexed_search_results(
        self,
        *,
        biosample_search: Optional[str] = None,
        organism: Optional[str] = None,
        assay_title: Optional[str] = None,
        target: Optional[str] = None,
        exclude_revoked: bool = True,
    ) -> list[dict[str, Any]]:
        """Use the optional search index to resolve a filtered summary list."""
        if self._search_index is None:
            return []

        summaries = self.get_experiment_summaries()
        all_accessions = set(self._summary_lookup.keys())
        candidate_sets: list[set[str]] = []

        if biosample_search:
            biosample_matches = self._search_index_matches("biosample_summary", biosample_search)
            biosample_matches.update(self._search_index_matches("biosample_term", biosample_search))
            candidate_sets.append(biosample_matches)

        if organism:
            candidate_sets.append(self._search_index_matches("organism", organism, exact=True))

        if assay_title:
            candidate_sets.append(self._search_index_matches("assay_title", assay_title, exact=True))

        if target:
            candidate_sets.append(self._search_index_matches("target", target))

        if exclude_revoked:
            candidate_sets.append(all_accessions - self._search_index_matches("status", "revoked", exact=True))

        matched_accessions = all_accessions
        for candidate_set in candidate_sets:
            matched_accessions &= candidate_set

        summary_by_accession = self._summary_lookup
        return [
            summary_by_accession[accession]
            for accession in (summary.get("accession") for summary in summaries)
            if accession in matched_accessions and accession in summary_by_accession
        ]
    
    def _load_experiments(self) -> list[dict[str, Any]]:
        """Load experiments from cache or ENCODE API"""
        # Try to load from cache if enabled and not forcing refresh
        if self.use_cache and not self.force_refresh and self.cache_file.exists():
            try:
                print("Loading experiments from cache...")
                with open(self.cache_file, 'r') as f:
                    data = json.load(f)
                experiments = data.get('experiments', [])
                print(f"✓ Loaded {len(experiments):,} experiments from cache\n")
                return experiments
            except Exception as e:
                print(f"Warning: Could not load from cache ({e}). Downloading from API...\n")
        
        # Load from API
        print("Loading all experiments from ENCODE database...")
        print("(This may take a minute...)\n")
        
        response = _request_with_retry(self.url, params=self.query_params, timeout=120)
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('@graph'), list):
            raise ENCODEValidationError("ENCODE experiments response did not contain an '@graph' list")
        
        experiments = data.get('@graph', [])
        print(f"✓ Loaded {len(experiments):,} total experiments\n")
        
        # Save to cache if caching is enabled
        if self.use_cache:
            self._save_cache(experiments)
        
        return experiments
    
    def _save_cache(self, experiments: list[dict[str, Any]]) -> None:
        """Save experiments to cache file"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {'experiments': experiments}
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f)
            self._save_summary_cache(self._derive_experiment_summaries(experiments))
            print(f"✓ Cached experiments to {self.cache_file}\n")
        except Exception as e:
            print(f"Warning: Could not save cache ({e})\n")
    
    def save(self, filepath: Optional[str] = None) -> Path:
        """
        Save the current experiments list to a file.
        
        Parameters:
        - filepath: Path to save to (default: ~/.encode_cache/experiments.json)
        
        Returns:
        - Path to saved file
        """
        if filepath is None:
            filepath = self.cache_file
        else:
            filepath = Path(filepath)
        
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {'experiments': self.experiments}
            with open(filepath, 'w') as f:
                json.dump(cache_data, f)
            print(f"✓ Saved {len(self.experiments):,} experiments to {filepath}")
            return filepath
        except Exception as e:
            raise IOError(f"Could not save experiments to {filepath}: {e}")
    
    def clear_cache(self, cache_dir: Optional[str] = None) -> None:
        """
        Clear the cache file.
        
        Parameters:
        - cache_dir: Cache directory to clear (default: self.cache_dir)
        """
        target_cache = Path(cache_dir) if cache_dir else self.cache_dir
        cache_file = target_cache / "experiments.json"
        summary_cache_file = target_cache / "experiment_summaries.json"
        
        try:
            if cache_file.exists():
                cache_file.unlink()
                print(f"✓ Cleared cache at {cache_file}")
            else:
                print(f"Cache file not found at {cache_file}")

            if summary_cache_file.exists():
                summary_cache_file.unlink()

            self._experiments = []
            self._experiments_loaded = False
            self._set_experiment_summaries([])
        except Exception as e:
            raise IOError(f"Could not clear cache: {e}")
    
    def _get_metadata_cache_path(self, accession: str) -> Path:
        """
        Get the cache file path for an experiment's metadata.
        
        Uses hierarchical structure: metadata/{exp_type_prefix}/{accession}.json
        For example: ENCSR000CDC -> metadata/SR/ENCSR000CDC.json
        
        Parameters:
        - accession: Experiment accession (e.g., 'ENCSR000CDC')
        
        Returns:
        - Path object for the cache file
        """
        if not accession or len(accession) < 5 or not accession.startswith('ENC'):
            raise ValueError(f"Invalid accession format: {accession}")
        
        # Extract type prefix (e.g., 'SR' from 'ENCSR000CDC')
        type_prefix = accession[3:5]
        cache_path = self.metadata_cache_dir / type_prefix / f"{accession}.json"
        return cache_path
    
    def _save_experiment_metadata(self, accession: str, data: dict[str, Any]) -> None:
        """
        Save experiment metadata to cache.
        
        Parameters:
        - accession: Experiment accession
        - data: Experiment data dictionary
        """
        cache_path = self._get_metadata_cache_path(accession)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Could not save experiment metadata for %s (%s)", accession, e)
    
    def _load_experiment_metadata(self, accession: str) -> Optional[dict[str, Any]]:
        """
        Load experiment metadata from cache.
        
        Parameters:
        - accession: Experiment accession
        
        Returns:
        - Dictionary with experiment data, or None if not cached
        """
        if not self.use_cache:
            return None
        
        cache_path = self._get_metadata_cache_path(accession)
        try:
            if cache_path.exists():
                self._record_instance_metric("metadata_cache_hits")
                with open(cache_path, 'r') as f:
                    return json.load(f)
        except Exception as exc:
            logger.warning("Could not load experiment metadata for %s (%s)", accession, exc)

        self._record_instance_metric("metadata_cache_misses")
        
        return None
    
    def clear_metadata_cache(self, accession: Optional[str] = None) -> None:
        """
        Clear metadata cache for specific experiment or all experiments.
        
        Parameters:
        - accession: Specific experiment accession to clear (default: None clears all)
        """
        try:
            if accession:
                cache_path = self._get_metadata_cache_path(accession)
                if cache_path.exists():
                    cache_path.unlink()
                    print(f"✓ Cleared metadata cache for {accession}")
            else:
                # Clear all metadata cache
                if self.metadata_cache_dir.exists():
                    import shutil
                    shutil.rmtree(self.metadata_cache_dir)
                    print(f"✓ Cleared all metadata cache at {self.metadata_cache_dir}")
        except Exception as e:
            raise IOError(f"Could not clear metadata cache: {e}")
    
    def get_metadata_cache_stats(self) -> dict[str, Any]:
        """
        Get statistics about the metadata cache.
        
        Returns:
        - Dictionary with cache statistics:
          {
            'cache_dir': Path to cache directory,
            'total_cached_experiments': Number of cached experiment metadata files,
            'cache_size_mb': Total size of cache in MB,
            'type_prefixes': Dict of {prefix: count} for each experiment type
          }
        """
        stats = {
            'cache_dir': str(self.metadata_cache_dir),
            'total_cached_experiments': 0,
            'cache_size_bytes': 0,
            'type_prefixes': {}
        }
        
        if not self.metadata_cache_dir.exists():
            return stats
        
        for type_dir in self.metadata_cache_dir.iterdir():
            if type_dir.is_dir():
                type_prefix = type_dir.name
                prefix_count = 0
                for cache_file in type_dir.glob('*.json'):
                    if cache_file.is_file():
                        stats['total_cached_experiments'] += 1
                        stats['cache_size_bytes'] += cache_file.stat().st_size
                        prefix_count += 1
                if prefix_count > 0:
                    stats['type_prefixes'][type_prefix] = prefix_count
        
        stats['cache_size_mb'] = round(stats['cache_size_bytes'] / (1024 * 1024), 2)
        return stats
    
    def create_experiment_object(self, experiment_data: dict[str, Any]) -> encodeExperiment:
        """
        Create an encodeExperiment object directly from experiment data.
        
        Parameters:
        - experiment_data: Full experiment dict from ENCODE API
        
        Returns:
        - encodeExperiment object
        
        This is useful for avoiding redundant API calls when you already have
        the experiment data loaded (e.g., from _load_experiments).
        """
        return encodeExperiment(experiment_data=experiment_data, encode_obj=self)

    def get_performance_stats(self) -> dict[str, Any]:
        """Return lightweight performance and cache statistics for this instance."""
        return {
            "version": __version__,
            "load_mode": self.load_mode,
            "metrics_enabled": _METRICS_ENABLED,
            "global_http": dict(_GLOBAL_METRICS),
            "instance_metrics": dict(self._instance_metrics),
            "loaded_experiments": len(self.get_loaded_experiments()),
            "loaded_summaries": len(self._experiment_summaries),
            "incremental_offset": self._incremental_offset,
            "search_index": self.get_search_index_stats(),
        }
    
    def getExperiment(self, accession: str) -> encodeExperiment:
        """
        Create an encodeExperiment object from an experiment accession.
        
        Parameters:
        - accession: ENCODE experiment accession (e.g., 'ENCSR000CDC')
        
        Returns:
        - encodeExperiment object
        
        This is a convenience method equivalent to:
            encodeExperiment(accession=accession, encode_obj=self)
        
        Example:
            exp = encode.getExperiment('ENCSR000CDC')
        """
        return encodeExperiment(accession=accession, encode_obj=self)
    
    def get_organism_from_experiment(self, exp: dict[str, Any]) -> Optional[str]:
        """Extract organism scientific name from experiment replicates"""
        organism = exp.get('organism')
        if isinstance(organism, str) and organism:
            return organism

        if 'replicates' not in exp or not exp['replicates']:
            return None
        
        for replicate in exp['replicates']:
            if 'library' in replicate and replicate['library']:
                lib = replicate['library']
                if 'biosample' in lib and lib['biosample']:
                    biosample = lib['biosample']
                    if 'organism' in biosample and biosample['organism']:
                        return biosample['organism'].get('scientific_name')
        return None
    
    def count_replicates(self, experiment: dict[str, Any]) -> int:
        """Count the number of replicates in an experiment"""
        replicates = experiment.get('replicates', [])
        return len(replicates) if replicates else 0
    
    def is_revoked(self, experiment: dict[str, Any]) -> bool:
        """Check if an experiment is revoked"""
        status = experiment.get('status', '')
        return status == 'revoked'
    
    def get_targets(self, experiment: dict[str, Any]) -> list[str]:
        """Extract target(s) from an experiment
        
        Returns a list of target labels. For most experiments, there's one target.
        Some experiments may have multiple targets.
        """
        explicit_targets = experiment.get('targets')
        if isinstance(explicit_targets, list):
            return [target for target in explicit_targets if isinstance(target, str) and target]

        target_field = experiment.get('target', None)
        
        if not target_field:
            return []
        
        # Handle single target (dict)
        if isinstance(target_field, dict):
            label = target_field.get('label', '')
            return [label] if label else []
        
        # Handle multiple targets (list)
        if isinstance(target_field, list):
            labels = []
            for target in target_field:
                if isinstance(target, dict):
                    label = target.get('label', '')
                    if label:
                        labels.append(label)
                elif isinstance(target, str):
                    labels.append(target)
            return labels
        
        # Handle string target
        if isinstance(target_field, str):
            return [target_field]
        
        return []
    
    def has_target(self, experiment: dict[str, Any]) -> bool:
        """Check if an experiment has a target"""
        return len(self.get_targets(experiment)) > 0
    
    def search_experiments_by_organism(
        self,
        organism: str,
        search_term: Optional[str] = None,
        experiments_list: Optional[list[dict[str, Any]]] = None,
        assay_title: Optional[str] = None,
        target: Optional[str] = None,
        exclude_revoked: bool = True,
        return_objects: bool = True,
    ) -> list[encodeExperiment] | list[dict[str, Any]]:
        """
        Search for experiments by organism.
        
        Parameters:
        - organism: 'Homo sapiens', 'Mus musculus'
        - search_term: Cell type or tissue name to search for (e.g., 'GM12878', 'Heart', 'K562')
        - experiments_list: List of experiments to search in (default: all loaded experiments)
        - assay_title: Filter by assay type (e.g., 'polyA plus RNA-seq', 'TF ChIP-seq')
        - target: Filter by target name (partial match, case-insensitive)
        - exclude_revoked: Exclude revoked experiments (default: True)
        - return_objects: Return encodeExperiment objects (True) or raw dicts (False)
        
        Returns:
        - List of encodeExperiment objects or raw experiment dicts
        """
        self._record_instance_metric("search_calls")

        if experiments_list is None and self._search_index is not None:
            indexed_matches = self._get_indexed_search_results(
                biosample_search=search_term,
                organism=organism,
                assay_title=assay_title,
                target=target,
                exclude_revoked=exclude_revoked,
            )
            experiments_list = indexed_matches
        else:
            experiments_list = self._get_search_source(experiments_list)
        
        search_lower = search_term.lower() if search_term else None
        matching = []
        
        assay_lower = assay_title.lower() if assay_title else None

        for exp in experiments_list:
            # Skip revoked experiments if requested
            if exclude_revoked and self.is_revoked(exp):
                continue

            exp_organism = self.get_organism_from_experiment(exp)
            if exp_organism != organism:
                continue           

            # Filter by search term if specified
            if search_lower:
                biosample_summary = exp.get('biosample_summary', '').lower()
                term_name = exp.get('biosample_ontology', {}).get('term_name', '').lower()
            
                # Check if biosample matches
                if not (search_lower in biosample_summary or search_lower in term_name):
                    continue
            
            # Filter by assay type if specified
            if assay_lower:
                exp_assay = exp.get('assay_title', '').lower()
                if exp_assay != assay_lower:
                    continue
            
            # Filter by target if specified (partial match)
            if target:
                exp_targets = self.get_targets(exp)
                target_lower = target.lower()
                if not any(target_lower in t.lower() for t in exp_targets):
                    continue
            
            matching.append(exp)
        
        # Convert to encodeExperiment objects if requested
        if return_objects:
            return [self.create_experiment_object(exp) for exp in matching]
        return matching
    
    def search_experiments_by_biosample(
        self,
        search_term: str,
        experiments_list: Optional[list[dict[str, Any]]] = None,
        organism: Optional[str] = None,
        assay_title: Optional[str] = None,
        target: Optional[str] = None,
        exclude_revoked: bool = True,
        return_objects: bool = True,
    ) -> list[encodeExperiment] | list[dict[str, Any]]:
        """
        Search for experiments by cell type, tissue name, or target.
        
        Parameters:
        - search_term: Cell type or tissue name to search for (e.g., 'GM12878', 'Heart', 'K562')
        - experiments_list: List of experiments to search in (default: all loaded experiments)
        - organism: Filter by organism (e.g., 'Homo sapiens', 'Mus musculus')
        - assay_title: Filter by assay type (e.g., 'polyA plus RNA-seq', 'TF ChIP-seq')
        - target: Filter by target name (partial match, case-insensitive)
        - exclude_revoked: Exclude revoked experiments (default: True)
        - return_objects: Return encodeExperiment objects (True) or raw dicts (False)
        
        Returns:
        - List of encodeExperiment objects or raw experiment dicts
        """
        self._record_instance_metric("search_calls")

        if experiments_list is None and self._search_index is not None:
            indexed_matches = self._get_indexed_search_results(
                biosample_search=search_term,
                organism=organism,
                assay_title=assay_title,
                target=target,
                exclude_revoked=exclude_revoked,
            )
            experiments_list = indexed_matches
        else:
            experiments_list = self._get_search_source(experiments_list)
        
        search_lower = search_term.lower()

        assay_lower = None
        if assay_title:
            assay_lower = assay_title.lower()
        matching = []
        
        for exp in experiments_list:
            # Skip revoked experiments if requested
            if exclude_revoked and self.is_revoked(exp):
                continue
            
            biosample_summary = exp.get('biosample_summary', '').lower()
            term_name = exp.get('biosample_ontology', {}).get('term_name', '').lower()
            
            # Check if biosample matches
            if not (search_lower in biosample_summary or search_lower in term_name):
                continue
            
            # Filter by organism if specified
            if organism:
                exp_organism = self.get_organism_from_experiment(exp)
                if exp_organism != organism:
                    continue
            
            # Filter by assay type if specified
            if assay_lower:
                exp_assay = exp.get('assay_title', '').lower()
                if exp_assay != assay_lower:
                    continue
            
            # Filter by target if specified (partial match)
            if target:
                exp_targets = self.get_targets(exp)
                target_lower = target.lower()
                if not any(target_lower in t.lower() for t in exp_targets):
                    continue
            
            matching.append(exp)
        
        # Convert to encodeExperiment objects if requested
        if return_objects:
            return [self.create_experiment_object(exp) for exp in matching]
        return matching
     
    def search_experiments_by_target(
        self,
        target: str,
        experiments_list: Optional[list[dict[str, Any]]] = None,
        organism: Optional[str] = None,
        assay_title: Optional[str] = None,
        exclude_revoked: bool = True,
        return_objects: bool = True,
    ) -> list[encodeExperiment] | list[dict[str, Any]]:
        """
        Search for all experiments with a specific target (supports partial matching).
        
        Parameters:
        - target: Target name to search for (partial match, case-insensitive)
        - experiments_list: List of experiments to search in (default: all loaded experiments)
        - organism: Filter by organism (e.g., 'Homo sapiens', 'Mus musculus')
        - assay_title: Filter by assay type (e.g., 'TF ChIP-seq')
        - exclude_revoked: Exclude revoked experiments (default: True)
        - return_objects: Return encodeExperiment objects (True) or raw dicts (False)
        
        Returns:
        - List of encodeExperiment objects or raw experiment dicts
        """
        self._record_instance_metric("search_calls")

        if experiments_list is None and self._search_index is not None:
            indexed_matches = self._get_indexed_search_results(
                organism=organism,
                assay_title=assay_title,
                target=target,
                exclude_revoked=exclude_revoked,
            )
            experiments_list = indexed_matches
        else:
            experiments_list = self._get_search_source(experiments_list)
        
        target_lower = target.lower()
        matching = []
        
        for exp in experiments_list:
            # Skip revoked experiments if requested
            if exclude_revoked and self.is_revoked(exp):
                continue
            
            # Check if target matches (partial match)
            exp_targets = self.get_targets(exp)
            if not any(target_lower in t.lower() for t in exp_targets):
                continue
            
            # Filter by organism if specified
            if organism:
                exp_organism = self.get_organism_from_experiment(exp)
                if exp_organism != organism:
                    continue
            
            # Filter by assay type if specified
            if assay_title:
                exp_assay = exp.get('assay_title', '').lower()
                assay_lower = assay_title.lower()
                if exp_assay != assay_lower:
                    continue
            
            matching.append(exp)
        
        # Convert to encodeExperiment objects if requested
        if return_objects:
            return [self.create_experiment_object(exp) for exp in matching]
        return matching

    def search_experiments_batch(
        self,
        queries: list[dict[str, Any]],
        return_objects: bool = True,
    ) -> dict[str, list[encodeExperiment] | list[dict[str, Any]]]:
        """Run multiple experiment searches in one call.

        Each query dict should contain a ``mode`` of ``biosample``, ``organism``,
        or ``target`` plus the corresponding input value.
        """
        self._record_instance_metric("batch_search_calls")
        results: dict[str, list[encodeExperiment] | list[dict[str, Any]]] = {}

        for index, query in enumerate(queries):
            mode = query.get("mode", "biosample")
            key = query.get("name") or f"query_{index + 1}"

            if mode == "biosample":
                search_term = query.get("search_term") or query.get("value")
                if not search_term:
                    raise ENCODEValidationError("Batch biosample queries require 'search_term' or 'value'")
                results[key] = self.search_experiments_by_biosample(
                    search_term,
                    organism=query.get("organism"),
                    assay_title=query.get("assay_title"),
                    target=query.get("target"),
                    exclude_revoked=query.get("exclude_revoked", True),
                    return_objects=return_objects,
                )
            elif mode == "organism":
                organism = query.get("organism") or query.get("value")
                if not organism:
                    raise ENCODEValidationError("Batch organism queries require 'organism' or 'value'")
                results[key] = self.search_experiments_by_organism(
                    organism,
                    search_term=query.get("search_term"),
                    assay_title=query.get("assay_title"),
                    target=query.get("target"),
                    exclude_revoked=query.get("exclude_revoked", True),
                    return_objects=return_objects,
                )
            elif mode == "target":
                target_name = query.get("target") or query.get("value")
                if not target_name:
                    raise ENCODEValidationError("Batch target queries require 'target' or 'value'")
                results[key] = self.search_experiments_by_target(
                    target_name,
                    organism=query.get("organism"),
                    assay_title=query.get("assay_title"),
                    exclude_revoked=query.get("exclude_revoked", True),
                    return_objects=return_objects,
                )
            else:
                raise ENCODEValidationError(f"Unsupported batch search mode: {mode}")

        return results

    def get_experiment_facets(
        self,
        fields: Optional[list[str]] = None,
        experiments_list: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, dict[str, int]]:
        """Return counts for common experiment facets useful in UIs and MCP clients."""
        source = self._get_search_source(experiments_list)
        requested_fields = fields or [
            "assay_title",
            "biosample_summary",
            "organism",
            "status",
            "target",
        ]
        facets: dict[str, dict[str, int]] = {}

        for field in requested_fields:
            counts: dict[str, int] = defaultdict(int)
            for experiment in source:
                if field == "organism":
                    value = self.get_organism_from_experiment(experiment)
                    if value:
                        counts[value] += 1
                elif field == "target":
                    for target_name in self.get_targets(experiment):
                        counts[target_name] += 1
                else:
                    value = experiment.get(field)
                    if isinstance(value, str) and value:
                        counts[value] += 1

            facets[field] = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

        return facets

    def _experiment_row_for_export(self, experiment: dict[str, Any] | encodeExperiment) -> dict[str, Any]:
        """Normalize experiment data for export formats."""
        if isinstance(experiment, encodeExperiment):
            return {
                "accession": experiment.accession,
                "organism": experiment.organism,
                "assay_title": experiment.assay,
                "biosample_summary": experiment.biosample,
                "lab": experiment.lab,
                "status": experiment.status,
                "targets": ", ".join(experiment.targets),
                "replicate_count": experiment.replicate_count,
                "description": experiment.description,
                "link": experiment.link,
            }

        targets = self.get_targets(experiment)
        return {
            "accession": experiment.get("accession"),
            "organism": self.get_organism_from_experiment(experiment),
            "assay_title": experiment.get("assay_title"),
            "biosample_summary": experiment.get("biosample_summary"),
            "lab": experiment.get("lab", {}).get("title", "Unknown") if isinstance(experiment.get("lab"), dict) else experiment.get("lab"),
            "status": experiment.get("status"),
            "targets": ", ".join(targets),
            "replicate_count": len(experiment.get("replicates", [])),
            "description": experiment.get("description", ""),
            "link": f"https://www.encodeproject.org{experiment.get('@id', '')}" if experiment.get("@id") else None,
        }

    def export_experiments(
        self,
        filepath: str,
        experiments: Optional[list[dict[str, Any]] | list[encodeExperiment]] = None,
        format: str = "json",
    ) -> Path:
        """Export experiments to JSON, CSV, or TSV."""
        selected_experiments = experiments if experiments is not None else self._get_search_source()
        rows = [
            self._experiment_row_for_export(experiment)
            for experiment in selected_experiments
        ]

        output_path = Path(filepath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_format = format.lower()

        if normalized_format == "json":
            with open(output_path, "w") as handle:
                json.dump(rows, handle, indent=2)
        elif normalized_format in {"csv", "tsv"}:
            delimiter = "," if normalized_format == "csv" else "\t"
            fieldnames = [
                "accession",
                "organism",
                "assay_title",
                "biosample_summary",
                "lab",
                "status",
                "targets",
                "replicate_count",
                "description",
                "link",
            ]
            with open(output_path, "w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=delimiter)
                writer.writeheader()
                writer.writerows(rows)
        else:
            raise ENCODEValidationError(f"Unsupported export format: {format}")

        self._record_instance_metric("exports")
        return output_path
    
    def get_samples_dataframe(self, organism: Optional[str] = None, assay_type: Optional[list[str]] = None) -> pd.DataFrame:
        """
        Create and return a DataFrame of samples with optional filtering.
        
        Parameters:
        - organism: Filter by organism (e.g., 'Homo sapiens', 'Mus musculus'). If None, includes all.
        - assay_type: Filter by assay type in a list (e.g., ['polyA plus RNA-seq']). If None, includes all.
        
        Returns:
        - pandas DataFrame with columns: Accession, Organism, Assay Type, Description, Biosample, Lab, Status, URL
        """
        samples_data = []
        lower_assays = [assay.lower() for assay in assay_type] if assay_type else None
        
        for exp in self._get_search_source():
            exp_organism = self.get_organism_from_experiment(exp)
            exp_assay = exp.get('assay_title')
            
            # Apply organism filter if specified
            if organism and exp_organism != organism:
                continue
            
            # Apply assay type filter if specified
            if assay_type and exp_assay.lower() not in lower_assays:
                continue
            
            samples_data.append({
                'Accession': exp.get('accession'),
                'Organism': exp_organism,
                'Assay Type': exp_assay,
                'Description': exp.get('description', '')[:60] + '...' if exp.get('description') else '',
                'Biosample': exp.get('biosample_summary', ''),
                'Lab': exp.get('lab', {}).get('title', 'Unknown'),
                'Status': exp.get('status'),
                'URL': f"https://www.encodeproject.org{exp.get('@id', '')}"
            })
        
        return pd.DataFrame(samples_data)

    # ------------------------------------------------------------------
    # File-accession-level lookup (no experiment accession required)
    # ------------------------------------------------------------------

    def _fetch_file_info(self, file_accession: str) -> dict[str, Any]:
        """Fetch full metadata for a single file from the ENCODE API.

        Results are cached in ``_file_info_cache`` for the lifetime of this
        ``ENCODE`` instance.

        Parameters:
        - file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

        Returns:
        - Dictionary with all file metadata from the ENCODE API.

        Raises:
        - ValueError: If the accession format is invalid or the file is not found.
        """
        if not file_accession or not file_accession.startswith("ENCFF") or len(file_accession) < 6:
            raise ValueError(f"Invalid file accession format: {file_accession}")

        if file_accession in self._file_info_cache:
            return self._file_info_cache[file_accession]

        url = f"{self.base_url}/files/{file_accession}/"
        response = _request_with_retry(url, params={"format": "json"}, timeout=30)
        data: dict[str, Any] = response.json()
        if not isinstance(data, dict) or data.get("accession") != file_accession:
            raise ENCODEValidationError(f"Invalid file metadata returned for {file_accession}")

        self._file_info_cache[file_accession] = data
        return data

    def search_experiments_by_file_accession(
        self,
        file_accession: str,
    ) -> Optional[encodeExperiment]:
        """Look up the experiment that contains a given file accession.

        Not all ENCODE files belong to experiments — genome references,
        annotations, and other datasets will have a ``dataset`` field that
        points to a non-experiment path (e.g., ``/annotations/...``).  In
        that case this method returns ``None``.

        Parameters:
        - file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

        Returns:
        - An ``encodeExperiment`` object if the file belongs to an experiment,
          or ``None`` if the file exists but is not part of an experiment.

        Raises:
        - ValueError: If the file accession is invalid or not found on ENCODE.
        """
        file_info = self._fetch_file_info(file_accession)

        dataset = file_info.get("dataset", "")
        if isinstance(dataset, dict):
            dataset = dataset.get("@id", "")

        # dataset looks like "/experiments/ENCSR000CDC/" for experiment files
        if "/experiments/" in dataset:
            parts = dataset.strip("/").split("/")
            try:
                exp_accession = parts[parts.index("experiments") + 1]
            except (ValueError, IndexError):
                return None
            return self.getExperiment(exp_accession)

        # File exists but doesn't belong to an experiment
        return None

    def get_file_metadata(self, file_accession: str) -> Optional[dict[str, Any]]:
        """Get metadata for any ENCODE file by its accession.

        Works for **all** ENCODE files — experiment files, genome references,
        annotations, etc.  Does not require knowing the parent experiment.

        Parameters:
        - file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

        Returns:
        - Dictionary with full file metadata, or ``None`` if not found.
        """
        try:
            return self._fetch_file_info(file_accession)
        except (ValueError, requests.exceptions.HTTPError):
            return None

    def get_file_metadata_batch(self, file_accessions: list[str]) -> dict[str, Optional[dict[str, Any]]]:
        """Get file metadata for multiple ENCODE file accessions."""
        return {
            accession: self.get_file_metadata(accession)
            for accession in file_accessions
        }

    def get_file_url(self, file_accession: str) -> Optional[str]:
        """Get the download URL for any ENCODE file by its accession.

        Works for **all** ENCODE files — experiment files, genome references,
        annotations, etc.  Does not require knowing the parent experiment.

        Parameters:
        - file_accession: ENCODE file accession (e.g., 'ENCFF001RJK')

        Returns:
        - Full download URL string, or ``None`` if not found.
        """
        try:
            info = self._fetch_file_info(file_accession)
        except (ValueError, requests.exceptions.HTTPError):
            return None

        href = info.get("href")
        if href:
            return f"{self.base_url}{href}"
        return None

    def get_file_url_batch(self, file_accessions: list[str]) -> dict[str, Optional[str]]:
        """Get download URLs for multiple ENCODE file accessions."""
        return {
            accession: self.get_file_url(accession)
            for accession in file_accessions
        }

    def search_experiments_by_file_accessions(
        self,
        file_accessions: list[str],
        return_objects: bool = True,
    ) -> dict[str, Optional[encodeExperiment] | Optional[dict[str, Any]]]:
        """Resolve multiple file accessions to their parent experiments when available."""
        results: dict[str, Optional[encodeExperiment] | Optional[dict[str, Any]]] = {}
        for file_accession in file_accessions:
            experiment = self.search_experiments_by_file_accession(file_accession)
            if experiment is None:
                results[file_accession] = None
            elif return_objects:
                results[file_accession] = experiment
            else:
                results[file_accession] = experiment.get_all_metadata()
        return results
