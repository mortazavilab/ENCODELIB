import requests
import pandas as pd
from urllib.parse import urljoin
import json
import os
from pathlib import Path
from datetime import datetime


__version__ = "0.2"


class encodeExperiment:
    """Represents a single ENCODE experiment with its metadata."""
    
    def __init__(self, accession=None, encode_obj=None, experiment_data=None):
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
    
    def _load_data(self):
        """Load experiment data if not already provided"""
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
            for exp in self.encode_obj.experiments:
                if exp.get('accession') == self.accession:
                    self.experiment_data = exp
                    # Cache this data
                    self.encode_obj._save_experiment_metadata(self.accession, exp)
                    return
        
        # Fetch from API if not found in loaded experiments
        url = f"https://www.encodeproject.org/experiments/{self.accession}/"
        try:
            response = requests.get(url, params={"format": "json"}, timeout=30)
            response.raise_for_status()
            self.experiment_data = response.json()
            # Cache the fetched data
            if self.encode_obj:
                self.encode_obj._save_experiment_metadata(self.accession, self.experiment_data)
        except Exception as e:
            raise ValueError(f"Could not load experiment {self.accession}: {e}")
    
    def _fetch_full_data(self):
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
            response = requests.get(url, params={"format": "json", "frame": "embedded"}, timeout=30)
            response.raise_for_status()
            self.experiment_data = response.json()
            # Clear the files cache since we have new data
            self._files_by_type_cache = None
            # Cache the full data
            if self.encode_obj:
                self.encode_obj._save_experiment_metadata(self.accession, self.experiment_data)
            return True
        except Exception as e:
            raise ValueError(f"Could not fetch experiment {self.accession}: {e}")
    
    def _ensure_full_data(self):
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
    
    def _extract_metadata(self):
        """Extract relevant metadata from experiment data"""
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
    
    def _get_organism(self):
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
    
    def _get_targets(self):
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
    
    def __str__(self):
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
    
    def __repr__(self):
        """Return a developer-friendly representation"""
        return f"encodeExperiment(accession='{self.accession}')"
    
    def to_dict(self):
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
    
    def get_all_metadata(self):
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
    
    def get_files_by_type(self, after_date=None, file_status='released'):
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
    
    def get_file_accessions_by_type(self, after_date=None, file_types=None):
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
    
    def get_file_types(self):
        """
        Get the list of available file types in this experiment.
        
        Returns:
        - List of file types (e.g., ['bam', 'bigWig', 'bed narrowPeak', 'fastq'])
          sorted alphabetically
        """
        files_by_type = self.get_files_by_type()
        return sorted(files_by_type.keys())
    
    def get_available_output_categories(self):
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
    
    def get_available_output_types(self):
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
    
    def get_file_accessions_by_output_category(self, output_categories=None):
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
    
    def get_file_accessions_by_output_type(self, output_types=None):
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
    
    def get_file_metadata(self, accession):
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
    
    def get_file_url(self, accession):
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
    
    def get_files_summary(self, max_files_per_type=None):
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
    
    def clear_cache(self, refresh=False):
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
    
    def download_files(self, output_dir, file_types=None, accessions=None):
        """
        Download files from this experiment to a local directory.
        
        Automatically ensures experiment metadata is loaded before attempting downloads.
        
        Parameters:
        - output_dir: Path to directory where files will be saved (will be created if doesn't exist)
        - file_types: str or list of str specifying file types to download (e.g., 'fastq', ['bam', 'bigWig'])
                      If None and accessions is None, all files are downloaded
        - accessions: str or list of str specifying specific file accessions to download (e.g., 'ENCFF001JZK')
                      Takes precedence over file_types if both specified
        
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
        
        # Get all files by type
        files_by_type = self.get_files_by_type()
        
        # Normalize inputs
        if file_types is not None and isinstance(file_types, str):
            file_types = [file_types]
        if accessions is not None and isinstance(accessions, str):
            accessions = [accessions]
        
        # Collect files to download
        files_to_download = []
        
        if accessions:
            # Download specific accessions
            for file_type, files in files_by_type.items():
                for file_obj in files:
                    if file_obj.get('accession') in accessions:
                        files_to_download.append(file_obj)
        elif file_types:
            # Download specific file types
            for file_type in file_types:
                if file_type in files_by_type:
                    files_to_download.extend(files_by_type[file_type])
        else:
            # Download all files
            for file_type, files in files_by_type.items():
                files_to_download.extend(files)
        
        # Download files
        downloaded = []
        failed = []
        skipped = []
        
        print(f"Downloading {len(files_to_download)} file(s) to {output_path}")
        
        for i, file_obj in enumerate(files_to_download, 1):
            accession = file_obj.get('accession')
            
            # Try to get filename from 'filename' field, or extract from 'href'
            filename = file_obj.get('filename')
            if not filename:
                # Extract filename from href (e.g., /files/ENCFF001JZK/@@download/ENCFF001JZK.fastq.gz -> ENCFF001JZK.fastq.gz)
                href = file_obj.get('href', '')
                if href and '@@download/' in href:
                    filename = href.split('@@download/')[-1]
            
            if not accession or not filename:
                skipped.append(accession or 'unknown')
                continue
            
            # Sanitize filename to prevent path traversal
            # Remove any directory components and only keep the base filename
            filename = os.path.basename(filename)
            if not filename or filename.startswith('.') or '/' in filename or '\\' in filename:
                failed.append((accession, "Invalid or unsafe filename"))
                continue
            
            file_path = output_path / filename
            
            # Check if file already exists
            if file_path.exists():
                print(f"  [{i}/{len(files_to_download)}] {accession} ({filename}) - SKIPPED (exists)")
                skipped.append(accession)
                continue
            
            try:
                # Get download URL
                url = file_obj.get('href')
                if not url:
                    failed.append((accession, "No download URL (href) found"))
                    continue
                
                if not url.startswith('http'):
                    url = f"https://www.encodeproject.org{url}"
                
                # Download file
                print(f"  [{i}/{len(files_to_download)}] Downloading {accession} ({filename})...", end='')
                
                response = requests.get(url, timeout=300, stream=True)
                response.raise_for_status()
                
                file_size = 0
                temp_path = output_path / f"{filename}.tmp"
                with open(temp_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            file_size += len(chunk)
                
                # Rename temp file to final name only after successful download
                temp_path.rename(file_path)
                downloaded.append(accession)
                print(f" DONE ({file_size:,} bytes)")
                
            except Exception as e:
                failed.append((accession, str(e)))
                print(f" FAILED ({e})")
                # Remove partially downloaded file
                if 'temp_path' in locals() and temp_path.exists():
                    temp_path.unlink()
                elif file_path.exists():
                    file_path.unlink()
        
        # Print summary
        print(f"\nDownload Summary:")
        print(f"  Downloaded: {len(downloaded)}")
        print(f"  Failed: {len(failed)}")
        print(f"  Skipped: {len(skipped)}")
        
        if failed:
            print(f"\nFailed downloads:")
            for accession, error in failed:
                print(f"  {accession}: {error}")
        
        return {
            'downloaded': downloaded,
            'failed': failed,
            'skipped': skipped,
            'output_dir': str(output_path)
        }


class ENCODE:
    """ENCODE Portal API interface for querying experiments and retrieving data."""
    
    BASE_URL = "https://www.encodeproject.org"
    CACHE_DIR = Path.home() / ".encode_cache"
    CACHE_FILE = CACHE_DIR / "experiments.json"
    METADATA_CACHE_DIR = CACHE_DIR / "metadata"  # Hierarchical cache for individual experiment metadata
    
    def __init__(self, use_cache=True, force_refresh=False, cache_dir=None):
        """
        Initialize ENCODE object by loading all experiments from the ENCODE database.
        
        Parameters:
        - use_cache: Use cached experiments if available (default: True)
        - force_refresh: Force downloading from API, ignore cache (default: False)
        - cache_dir: Custom cache directory (default: ~/.encode_cache)
        """
        self.base_url = self.BASE_URL
        self.url = f"{self.base_url}/experiments/"
        self.query_params = {
            "format": "json",
            "limit": "all"  # Get all results
        }
        self.use_cache = use_cache
        self.force_refresh = force_refresh
        
        # Set cache file location
        if cache_dir:
            self.cache_dir = Path(cache_dir)
            self.cache_file = self.cache_dir / "experiments.json"
            self.metadata_cache_dir = self.cache_dir / "metadata"
        else:
            self.cache_dir = self.CACHE_DIR
            self.cache_file = self.CACHE_FILE
            self.metadata_cache_dir = self.METADATA_CACHE_DIR
        
        self.experiments = self._load_experiments()
    
    def _load_experiments(self):
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
        
        response = requests.get(self.url, params=self.query_params, timeout=120)
        response.raise_for_status()
        data = response.json()
        
        experiments = data.get('@graph', [])
        print(f"✓ Loaded {len(experiments):,} total experiments\n")
        
        # Save to cache if caching is enabled
        if self.use_cache:
            self._save_cache(experiments)
        
        return experiments
    
    def _save_cache(self, experiments):
        """Save experiments to cache file"""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {'experiments': experiments}
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f)
            print(f"✓ Cached experiments to {self.cache_file}\n")
        except Exception as e:
            print(f"Warning: Could not save cache ({e})\n")
    
    def save(self, filepath=None):
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
    
    def clear_cache(self, cache_dir=None):
        """
        Clear the cache file.
        
        Parameters:
        - cache_dir: Cache directory to clear (default: self.cache_dir)
        """
        target_cache = Path(cache_dir) if cache_dir else self.cache_dir
        cache_file = target_cache / "experiments.json"
        
        try:
            if cache_file.exists():
                cache_file.unlink()
                print(f"✓ Cleared cache at {cache_file}")
            else:
                print(f"Cache file not found at {cache_file}")
        except Exception as e:
            raise IOError(f"Could not clear cache: {e}")
    
    def _get_metadata_cache_path(self, accession):
        """
        Get the cache file path for an experiment's metadata.
        
        Uses hierarchical structure: metadata/{exp_type_prefix}/{accession}.json
        For example: ENCSR000CDC -> metadata/SR/ENCSR000CDC.json
        
        Parameters:
        - accession: Experiment accession (e.g., 'ENCSR000CDC')
        
        Returns:
        - Path object for the cache file
        """
        if not accession or len(accession) < 5:
            raise ValueError(f"Invalid accession format: {accession}")
        
        # Extract type prefix (e.g., 'SR' from 'ENCSR000CDC')
        type_prefix = accession[3:5]
        cache_path = self.metadata_cache_dir / type_prefix / f"{accession}.json"
        return cache_path
    
    def _save_experiment_metadata(self, accession, data):
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
            # Silently fail on cache write - it's not critical
            pass
    
    def _load_experiment_metadata(self, accession):
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
                with open(cache_path, 'r') as f:
                    return json.load(f)
        except Exception:
            # Silently fail on cache read - fall back to API
            pass
        
        return None
    
    def clear_metadata_cache(self, accession=None):
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
    
    def get_metadata_cache_stats(self):
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
    
    def create_experiment_object(self, experiment_data):
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
    
    def getExperiment(self, accession):
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
    
    def get_organism_from_experiment(self, exp):
        """Extract organism scientific name from experiment replicates"""
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
    
    def count_replicates(self, experiment):
        """Count the number of replicates in an experiment"""
        replicates = experiment.get('replicates', [])
        return len(replicates) if replicates else 0
    
    def is_revoked(self, experiment):
        """Check if an experiment is revoked"""
        status = experiment.get('status', '')
        return status == 'revoked'
    
    def get_targets(self, experiment):
        """Extract target(s) from an experiment
        
        Returns a list of target labels. For most experiments, there's one target.
        Some experiments may have multiple targets.
        """
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
    
    def has_target(self, experiment):
        """Check if an experiment has a target"""
        return len(self.get_targets(experiment)) > 0
    
    def search_experiments_by_organism(self, organism, search_term=None, experiments_list=None, assay_title=None, target=None, exclude_revoked=True, return_objects=True):
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

        if experiments_list is None:
            experiments_list = self.experiments
        
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
            return [encodeExperiment(exp.get('accession'), self) for exp in matching]
        return matching
    
    def search_experiments_by_biosample(self, search_term, experiments_list=None, organism=None, assay_title=None, target=None, exclude_revoked=True, return_objects=True):
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
        
        if experiments_list is None:
            experiments_list = self.experiments
        
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
            return [encodeExperiment(exp.get('accession'), self) for exp in matching]
        return matching
     
    def search_experiments_by_target(self, target, experiments_list=None, organism=None, assay_title=None, exclude_revoked=True, return_objects=True):
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
        if experiments_list is None:
            experiments_list = self.experiments
        
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
            return [encodeExperiment(exp.get('accession'), self) for exp in matching]
        return matching
    
    def get_samples_dataframe(self, organism=None, assay_type=None):
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
        
        for exp in self.experiments:
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

