# ENCODE Library Documentation

## Overview

`encodeLib.py` provides a Python interface to the ENCODE Portal API, allowing you to query, filter, and retrieve information about ENCODE experiments and their associated files. It consists of two main classes:

1. **`ENCODE`** - Manages loading and searching experiments from the ENCODE database
2. **`encodeExperiment`** - Represents a single experiment with its metadata and files

## Table of Contents

- [ENCODE Class](#encode-class)
- [encodeExperiment Class](#encodeexperiment-class)
- [Usage Examples](#usage-examples)

---

## ENCODE Class

The `ENCODE` class provides access to all experiments in the ENCODE database with caching support and comprehensive search functionality.

### Initialization

```python
from encodeLib import ENCODE

# Initialize with default settings (uses cache)
encode = ENCODE()

# Force refresh from API (ignore cache)
encode = ENCODE(force_refresh=True)

# Disable caching
encode = ENCODE(use_cache=False)

# Use custom cache directory
encode = ENCODE(cache_dir='/path/to/custom/cache')
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `experiments` | list | List of all loaded experiment dictionaries |
| `base_url` | str | Base URL for ENCODE API (https://www.encodeproject.org) |
| `cache_dir` | Path | Directory where experiments are cached |
| `cache_file` | Path | Path to the cache JSON file |
| `use_cache` | bool | Whether caching is enabled |

### Methods

#### `search_experiments_by_biosample()`

Search for experiments by cell type, tissue name, or biosample.

```python
# Basic search
gm12878_experiments = encode.search_experiments_by_biosample('GM12878')

# Search with filters
k562_chipseq = encode.search_experiments_by_biosample(
    'K562',
    assay_title='TF ChIP-seq',
    organism='Homo sapiens'
)

# Search without filters (return raw dicts instead of objects)
heart_raw = encode.search_experiments_by_biosample(
    'heart',
    return_objects=False
)

# Search including revoked experiments
all_results = encode.search_experiments_by_biosample(
    'K562',
    exclude_revoked=False
)
```

**Parameters:**
- `search_term` (str): Cell type or tissue name to search for
- `experiments_list` (list, optional): List to search in (default: all experiments)
- `organism` (str, optional): Filter by organism (e.g., 'Homo sapiens', 'Mus musculus')
- `assay_title` (str, optional): Filter by assay type (e.g., 'polyA plus RNA-seq')
- `target` (str, optional): Filter by target name (partial match, case-insensitive)
- `exclude_revoked` (bool, optional): Exclude revoked experiments (default: True)
- `return_objects` (bool, optional): Return encodeExperiment objects (True) or raw dicts (False)

**Returns:** List of `encodeExperiment` objects or raw experiment dictionaries

#### `search_experiments_by_target()`

Search for experiments by transcription factor or histone modification target.

```python
# Search for TP53 experiments
tp53_experiments = encode.search_experiments_by_target('TP53')

# Search for H3K27ac (histone acetylation)
h3k27ac = encode.search_experiments_by_target('H3K27ac')

# Search with filters
h3k27ac_human = encode.search_experiments_by_target(
    'H3K27ac',
    organism='Homo sapiens',
    assay_title='Histone ChIP-seq'
)

# Get raw dictionaries instead of objects
ctcf_raw = encode.search_experiments_by_target(
    'CTCF',
    return_objects=False
)
```

**Parameters:**
- `target` (str): Target name to search for (supports partial matching)
- `experiments_list` (list, optional): List to search in
- `organism` (str, optional): Filter by organism
- `assay_title` (str, optional): Filter by assay type
- `exclude_revoked` (bool, optional): Exclude revoked experiments
- `return_objects` (bool, optional): Return objects or raw dicts

**Returns:** List of `encodeExperiment` objects or raw experiment dictionaries

#### `get_samples_dataframe()`

Create a pandas DataFrame of experiments with optional filtering.

```python
import pandas as pd

# Get all experiments as DataFrame
df = encode.get_samples_dataframe()

# Filter by organism
human_df = encode.get_samples_dataframe(organism='Homo sapiens')

# Filter by assay type
rna_seq_df = encode.get_samples_dataframe(
    assay_type=['polyA plus RNA-seq', 'total RNA-seq']
)

# Combine filters
mouse_chipseq_df = encode.get_samples_dataframe(
    organism='Mus musculus',
    assay_type=['TF ChIP-seq']
)

# Display results
print(mouse_chipseq_df.head())
```

**Parameters:**
- `organism` (str, optional): Filter by organism
- `assay_type` (list, optional): List of assay types to include

**Returns:** pandas DataFrame with columns: Accession, Organism, Assay Type, Description, Biosample, Lab, Status, URL

#### `create_experiment_object()`

Create an `encodeExperiment` object from raw experiment data.

```python
# Useful when you already have experiment data loaded
raw_exp_data = encode.experiments[0]
exp_obj = encode.create_experiment_object(raw_exp_data)
print(exp_obj)
```

**Parameters:**
- `experiment_data` (dict): Raw experiment dictionary from API

**Returns:** `encodeExperiment` object

#### `getExperiment(accession)`

Create an `encodeExperiment` object from an experiment accession ID.

This is a convenience method for instantiating experiment objects.

```python
# Get an experiment by accession
exp = encode.getExperiment('ENCSR000CDC')
print(exp.assay)

# Equivalent to:
exp = encodeExperiment('ENCSR000CDC', encode_obj=encode)
```

**Parameters:**
- `accession` (str): ENCODE experiment accession (e.g., 'ENCSR000CDC')

**Returns:** `encodeExperiment` object

#### Helper Methods

```python
# Check if experiment is revoked
is_revoked = encode.is_revoked(experiment_dict)

# Get targets from experiment
targets = encode.get_targets(experiment_dict)

# Check if experiment has target
has_target = encode.has_target(experiment_dict)

# Count replicates
num_replicates = encode.count_replicates(experiment_dict)

# Get organism from experiment
organism = encode.get_organism_from_experiment(experiment_dict)
```

#### Cache Management

```python
# Save experiments to custom location
encode.save('/path/to/backup/experiments.json')

# Clear cache
encode.clear_cache()

# Clear cache from specific directory
encode.clear_cache(cache_dir='/custom/cache/path')
```

---

## encodeExperiment Class

The `encodeExperiment` class represents a single ENCODE experiment with all its metadata and file information.

### Initialization

```python
from encodeLib import ENCODE, encodeExperiment

# Initialize from accession (requires ENCODE object)
encode = ENCODE()
exp = encodeExperiment('ENCSR000CDC', encode)

# Initialize from accession without ENCODE object (fetches from API)
exp = encodeExperiment('ENCSR000CDC')

# Initialize from raw experiment data
raw_data = encode.experiments[0]
exp = encodeExperiment(experiment_data=raw_data, encode_obj=encode)
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `accession` | str | ENCODE experiment accession ID |
| `organism` | str | Scientific name of organism (e.g., 'Homo sapiens') |
| `assay` | str | Type of assay performed |
| `biosample` | str | Cell type or tissue used |
| `lab` | str | Lab that performed the experiment |
| `status` | str | Status of experiment (released, archived, revoked) |
| `targets` | list | List of targets (transcription factors, histone marks, etc.) |
| `description` | str | Experiment description |
| `replicate_count` | int | Number of replicates |
| `link` | str | URL to experiment on ENCODE portal |
| `experiment_data` | dict | Full raw data from ENCODE API |

### Methods

#### `get_files_by_type()`

Retrieve all files organized by file type with comprehensive metadata including genome annotations.

```python
# Get all files organized by type with full metadata
files_by_type = exp.get_files_by_type()

# Display comprehensive file information
for file_type, files in files_by_type.items():
    print(f"{file_type}: {len(files)} files")
    for file in files[:2]:
        print(f"  Accession: {file.get('accession')}")
        print(f"  Assembly: {file.get('assembly')}")
        print(f"  Genome Annotation: {file.get('genome_annotation', 'N/A')}")
        print(f"  Output Type: {file.get('output_type')}")
        print(f"  Derived From: {file.get('derived_from', [])}")

# Filter by date (files released after 2024-01-01)
recent_files = exp.get_files_by_type(after_date='2024-01-01')

# Filter by file status
archived_files = exp.get_files_by_type(file_status='archived')

# Access all available metadata
for file_type, files in files_by_type.items():
    for file in files[:1]:
        # Files contain all metadata from ENCODE API
        print(f"Available keys: {list(file.keys())[:10]}...")
```

**Parameters:**
- `after_date` (str, optional): Filter files released after this date (format: YYYY-MM-DD)
- `file_status` (str, optional): Filter by file status (default: 'released')

**Returns:** Dictionary with file type as key and list of file dictionaries as values. Each file dict contains comprehensive metadata:

**Common fields:**
- `accession`, `filename`, `title`, `file_type`, `file_format`, `file_size`

**Quality fields:**
- `status`, `preferred_default`, `md5sum`, `content_md5sum`

**Replicate fields:**
- `biological_replicates`, `technical_replicates`, `biological_replicates_formatted`

**Mapping & Assembly fields:**
- `mapped_read_length`, `mapped_run_type`, `read_length_units`, `assembly`, `genome_annotation`

**Data fields:**
- `output_type`, `output_category`, `derived_from`, `target`

**Administrative fields:**
- `date_released`, `date_created`, `uuid`, `schema_version`

**Plus all other fields available from the ENCODE API**

#### `get_file_types()`

Get the list of available file types for this experiment.

```python
# Get all available file types
file_types = exp.get_file_types()
print(f"Available file types: {file_types}")

# Output: ['bam', 'bed narrowPeak', 'bigBed narrowPeak', 'bigWig', 'fastq']

# Use for iterating through specific types
for ftype in exp.get_file_types():
    print(f"Processing {ftype} files...")
```

**Returns:** List of file type strings, sorted alphabetically (e.g., `['bam', 'bigWig', 'fastq']`)

#### `get_available_output_categories()`

Get the list of available output categories in the experiment (e.g., 'raw data', 'processed data').

```python
# Get all available output categories
categories = exp.get_available_output_categories()
print(f"Available output categories: {categories}")
# Output: ['processed data', 'raw data']
```

**Returns:** List of output category strings, sorted alphabetically.

#### `get_available_output_types()`

Get the list of available output types in the experiment (e.g., 'reads', 'alignments', 'peaks').

```python
# Get all available output types
output_types = exp.get_available_output_types()
print(f"Available output types: {output_types}")
# Output: ['alignments', 'peaks', 'reads', 'signal']
```

**Returns:** List of output type strings, sorted alphabetically.

#### `get_file_accessions_by_output_category(output_categories=None)`

Get file accessions organized by output category, with optional filtering.

```python
# Get all output categories and their accessions
all_categories = exp.get_file_accessions_by_output_category()
print(all_categories)
# Output:
# {
#   'raw data': ['ENCFF001AAA', 'ENCFF002BBB', ...],
#   'processed data': ['ENCFF003CCC', ...]
# }

# Get only specific categories
specific = exp.get_file_accessions_by_output_category(['raw data'])
print(specific)
# Output: {'raw data': ['ENCFF001AAA', 'ENCFF002BBB', ...]}
```

**Parameters:**
- `output_categories` (optional): List of categories to filter by. If `None`, returns all categories.

**Returns:** Dictionary with category as key and list of accessions as value.

#### `get_file_accessions_by_output_type(output_types=None)`

Get file accessions organized by output type, with optional filtering.

```python
# Get all output types and their accessions
all_types = exp.get_file_accessions_by_output_type()
print(all_types)
# Output:
# {
#   'reads': ['ENCFF001AAA', 'ENCFF002BBB', ...],
#   'alignments': ['ENCFF003CCC', ...],
#   'peaks': [...]
# }

# Get only specific output types
specific = exp.get_file_accessions_by_output_type(['alignments', 'peaks'])
print(specific)
# Output:
# {
#   'alignments': ['ENCFF003CCC', ...],
#   'peaks': [...]
# }
```

**Parameters:**
- `output_types` (optional): List of output types to filter by. If `None`, returns all types.

**Returns:** Dictionary with output type as key and list of accessions as value.

#### `get_file_metadata(accession)`

Get comprehensive metadata for a specific file accession.

```python
# Get metadata for a specific file
metadata = exp.get_file_metadata('ENCFF707OWJ')
if metadata:
    print(f"Filename: {metadata['filename']}")
    print(f"Output Type: {metadata['output_type']}")
    print(f"Assembly: {metadata['assembly']}")
else:
    print("File accession not found")
```

**Parameters:**
- `accession`: File accession ID (e.g., `'ENCFF001JZK'`)

**Returns:** Dictionary with all file metadata, or `None` if not found.

#### `get_file_url(accession)`

Get the download URL for a file accession.

```python
# Get download URL for a specific file
url = exp.get_file_url('ENCFF707OWJ')
if url:
    print(f"Download URL: {url}")
else:
    print("File accession not found")
```

**Parameters:**
- `accession`: File accession ID (e.g., `'ENCFF001JZK'`)

**Returns:** Full HTTPS URL for downloading the file, or `None` if not found.

#### `get_file_accessions_by_type()`

Get file accessions organized by file type, with optional filtering.

```python
# Get accessions for all file types
all_accessions = exp.get_file_accessions_by_type()

for file_type, accessions in sorted(all_accessions.items()):
    print(f"{file_type}: {accessions}")

# Get accessions for specific file types only
bam_and_bw = exp.get_file_accessions_by_type(file_types=['bam', 'bigWig'])

print(f"BAM files: {bam_and_bw.get('bam', [])}")
print(f"BigWig files: {bam_and_bw.get('bigWig', [])}")

# Filter by date and file type
recent_bam = exp.get_file_accessions_by_type(
    after_date='2024-01-01',
    file_types=['bam']
)
```

**Parameters:**
- `after_date` (str, optional): Filter files released after this date (format: YYYY-MM-DD)
- `file_types` (list, optional): List of file types to include (e.g., `['bam', 'bigWig']`). If None, returns all file types.

**Returns:** Dictionary with file type as key and list of file accessions as values

#### `get_files_summary()`

Get a summary view of files with all details by default.

```python
# Get summary of all files (default behavior)
summary = exp.get_files_summary()

for file_type, info in summary.items():
    print(f"{file_type} ({info['count']} total):")
    for file in info['files']:
        print(f"  {file['filename']} - {file['file_size']:,} bytes")

# Limit files shown per type (e.g., show only first 3)
limited_summary = exp.get_files_summary(max_files_per_type=3)
```

**Parameters:**
- `max_files_per_type` (int, optional): Maximum files to show per type (default: None = all files)

**Returns:** Dictionary with file type as key and summary dict as value

#### `to_dict()`

Get experiment metadata as a dictionary.

```python
exp_dict = exp.to_dict()
print(exp_dict)

# Output:
# {
#   'Accession': 'ENCSR000CDC',
#   'Organism': 'Homo sapiens',
#   'Assay': 'polyA plus RNA-seq',
#   'Targets': [''],
#   'Biosample': 'CD20+ B cells',
#   'Lab': 'Gingeras',
#   'Status': 'released',
#   'Replicates': 2,
#   'Description': '...',
#   'Link': 'https://www.encodeproject.org/experiments/ENCSR000CDC/'
# }
```

#### `get_all_metadata()`

Get all available metadata from the ENCODE API for this experiment.

```python
# Get complete raw data from ENCODE API
all_metadata = exp.get_all_metadata()

# This includes everything available via the API:
print(f"Total fields: {len(all_metadata)}")

# Access specific fields
print(f"Assembly: {all_metadata.get('assembly')}")
print(f"Date released: {all_metadata.get('date_released')}")
print(f"Number of files: {len(all_metadata.get('files', []))}")
print(f"DOI: {all_metadata.get('doi')}")
print(f"Related series: {all_metadata.get('related_series')}")
print(f"Replication type: {all_metadata.get('replication_type')}")

# List all available keys
print("Available metadata fields:")
for key in sorted(all_metadata.keys()):
    print(f"  {key}")
```

**Returns:** Dictionary with all metadata from ENCODE API, including:
- Basic experiment info: accession, status, description, date_released
- Scientific info: organism, assay_title, target, biosample_summary
- File references: files (complete file objects with all metadata)
- Replicate info: replicates, bio_replicate_count, tech_replicate_count
- Related data: related_series, related_annotations, possible_controls
- Administrative: award, lab, submitted_by, schema_version, uuid
- Plus all other fields returned by the ENCODE API

#### Display Methods

```python
# Pretty-print experiment details
print(exp)

# Output:
# ================================================================================
# ENCODE Experiment: ENCSR000CDC
# ================================================================================
# Organism:        Homo sapiens
# Assay:           polyA plus RNA-seq
# Target:          None
# Biosample:       CD20+ B cells
# Lab:             Gingeras
# Status:          released
# Replicates:      2
# Description:     A total of 28 RNA samples were prepared from the B cells...
# Link:            https://www.encodeproject.org/experiments/ENCSR000CDC/
# ================================================================================

# Get brief representation
print(repr(exp))
# Output: encodeExperiment(accession='ENCSR000CDC')
```

#### `download_files(output_dir, file_types=None, accessions=None)`

Download files from this experiment to a local directory.

Automatically ensures experiment metadata is loaded before attempting downloads. Files that already exist locally are skipped.

```python
from encodeLib import ENCODE

encode = ENCODE()
exp = encode.getExperiment('ENCSR000CDC')

# Download all fastq files
result = exp.download_files('/path/to/output', file_types='fastq')

# Download multiple file types
result = exp.download_files('/path/to/output', file_types=['fastq', 'bam'])

# Download specific files by accession
result = exp.download_files('/path/to/output', accessions=['ENCFF001JZK', 'ENCFF002ABC'])

# Download a single file
result = exp.download_files('/path/to/output', accessions='ENCFF001JZK')

# Download all files
result = exp.download_files('/path/to/output')

# Check results
print(f"Downloaded: {len(result['downloaded'])} files")
print(f"Failed: {len(result['failed'])}")
print(f"Skipped: {len(result['skipped'])}")
```

**Parameters:**
- `output_dir` (str or Path): Directory where files will be saved (created if doesn't exist)
- `file_types` (str or list, optional): File type(s) to download (e.g., `'fastq'`, `['bam', 'bigWig']`). If None and accessions is None, all files are downloaded.
- `accessions` (str or list, optional): Specific file accession(s) to download (e.g., `'ENCFF001JZK'`, `['ENCFF001JZK', 'ENCFF002ABC']`). Takes precedence over file_types if both specified.

**Returns:** Dictionary with download results:
```python
{
    'downloaded': ['ENCFF001JZK', 'ENCFF002ABC'],      # Successfully downloaded accessions
    'failed': [('ENCFF003DEF', 'Connection timeout')], # Failed accessions with error messages
    'skipped': ['ENCFF004GHI'],                        # Accessions skipped (already exist)
    'output_dir': '/path/to/output'                    # Output directory path
}
```

---

## Usage Examples

### Example 1: Find all ChIP-seq experiments for a transcription factor

```python
from encodeLib import ENCODE

encode = ENCODE()

# Find all TP53 ChIP-seq experiments
tp53_chipseq = encode.search_experiments_by_target(
    'TP53',
    assay_title='TF ChIP-seq'
)

print(f"Found {len(tp53_chipseq)} TP53 ChIP-seq experiments")

for exp in tp53_chipseq:
    print(f"{exp.accession}: {exp.biosample} ({exp.organism})")
```

### Example 2: Retrieve and organize files from an experiment

```python
from encodeLib import ENCODE

encode = ENCODE()
exp = encode.getExperiment('ENCSR160HKZ')

print(f"Experiment: {exp.accession}")
print(f"Assay: {exp.assay}")
print(f"Organism: {exp.organism}")

# Get available file types
print(f"\nAvailable file types: {exp.get_file_types()}")

# Get files organized by type
files_by_type = exp.get_files_by_type()

print(f"\nTotal files: {sum(len(f) for f in files_by_type.values())}")
print(f"File types:")
for file_type, files in files_by_type.items():
    total_size = sum(f['file_size'] for f in files)
    print(f"  {file_type}: {len(files)} files ({total_size:,} bytes)")

# Show detailed file information
for file_type, files in files_by_type.items():
    if files:
        sample_file = files[0]
        print(f"\nSample {file_type} file:")
        print(f"  Accession: {sample_file['accession']}")
        print(f"  Assembly: {sample_file.get('assembly')}")
        print(f"  Read length: {sample_file.get('mapped_read_length')}")
        print(f"  Replicates: {sample_file.get('biological_replicates')}")

# Get accessions for specific file types only
bam_accessions = exp.get_file_accessions_by_type(file_types=['bam'])
print(f"\nBAM file accessions: {bam_accessions.get('bam', [])}")
```

### Example 3: Search and filter experiments

```python
from encodeLib import ENCODE
import pandas as pd

encode = ENCODE()

# Find all K562 cell line RNA-seq experiments
k562_rna = encode.search_experiments_by_biosample(
    'K562',
    assay_title='polyA plus RNA-seq',
    organism='Homo sapiens'
)

print(f"Found {len(k562_rna)} K562 polyA RNA-seq experiments")

# Get as DataFrame for further analysis
df = encode.get_samples_dataframe(organism='Homo sapiens')
k562_df = df[df['Biosample'].str.contains('K562', case=False)]

print(k562_df[['Accession', 'Assay Type', 'Lab']].head(10))
```

### Example 4: Extract experiment metadata

```python
from encodeLib import ENCODE

# Create experiment from accession
encode = ENCODE()
exp = encode.getExperiment('ENCSR000CDC')

# Display all metadata
print(exp)

# Get specific information
print(f"Accession: {exp.accession}")
print(f"Assay: {exp.assay}")
print(f"Replicates: {exp.replicate_count}")
print(f"Targets: {', '.join(exp.targets) if exp.targets else 'None'}")

# Convert to dictionary for further processing
metadata = exp.to_dict()
print(metadata)
```

### Example 5: Working with files and dates

```python
from encodeLib import ENCODE

encode = ENCODE()
exp = encode.getExperiment('ENCSR160HKZ')

# Get all files
all_files = exp.get_files_by_type()
print(f"Total files: {sum(len(f) for f in all_files.values())}")

# Get only recently released files
recent_files = exp.get_files_by_type(after_date='2024-01-01')
print(f"Files from 2024+: {sum(len(f) for f in recent_files.values())}")

# Get file summary
summary = exp.get_files_summary(max_files_per_type=3)
for file_type, info in summary.items():
    print(f"\n{file_type} ({info['count']} total):")
    for aFile in info['files']:
        print(f"  {aFile['accession']} - {aFile['file_size']:,} bytes")
```

### Example 6: Batch processing experiments

```python
from encodeLib import ENCODE

encode = ENCODE()

# Search for heart tissue experiments
heart_exps = encode.search_experiments_by_biosample('heart')

# Process each experiment
for exp in heart_exps[:5]:  # Process first 5
    print(f"\n{exp.accession}: {exp.assay}")
    
    try:
        # Get files
        files = exp.get_files_by_type()
        print(f"  Files: {sum(len(f) for f in files.values())}")
        
        # Get file accessions
        accessions = exp.get_file_accessions_by_type()
        for file_type, accs in accessions.items():
            print(f"    {file_type}: {len(accs)} files")
    except Exception as e:
        print(f"  Error retrieving files: {e}")
```

### Example 7: Download files from an experiment

```python
from encodeLib import ENCODE
from pathlib import Path

encode = ENCODE()
exp = encode.getExperiment('ENCSR000CDC')

# Download all fastq files
result = exp.download_files('./data/fastq_files', file_types='fastq')
print(f"Downloaded {len(result['downloaded'])} fastq files")
if result['failed']:
    print(f"Failed: {len(result['failed'])} files")

# Download multiple file types
result = exp.download_files(
    './data/processed_files',
    file_types=['bam', 'bigWig']
)

# Download specific files by accession
result = exp.download_files(
    './data/specific_files',
    accessions=['ENCFF001JZK', 'ENCFF002ABC', 'ENCFF003DEF']
)

# Download a single file
result = exp.download_files(
    './data/single_file',
    accessions='ENCFF001JZK'
)

# Download all files
result = exp.download_files('./data/all_files')

# Check results
print(f"Summary:")
print(f"  Downloaded: {len(result['downloaded'])} files")
print(f"  Failed: {len(result['failed'])} files")
print(f"  Skipped: {len(result['skipped'])} files")
print(f"  Location: {result['output_dir']}")

# If there were failures, see what went wrong
if result['failed']:
    for accession, error in result['failed']:
        print(f"  {accession}: {error}")
```

---

## Caching

The ENCODE class uses local caching to speed up repeated queries:

- **Default behavior**: Experiments are cached to `~/.encode_cache/experiments.json` after first load
- **Cache location**: Customizable via `cache_dir` parameter
- **Force refresh**: Pass `force_refresh=True` to download fresh data from API
- **Disable caching**: Pass `use_cache=False` to skip caching entirely

```python
from encodeLib import ENCODE

# First run: Downloads from API, saves to cache (~30 seconds)
encode1 = ENCODE()

# Second run: Loads from cache (< 3 seconds)
encode2 = ENCODE()

# Force fresh download
encode3 = ENCODE(force_refresh=True)

# Disable caching
encode4 = ENCODE(use_cache=False)
```

---

## Performance Notes

- **Initial load**: First time loading all ~27,000 experiments takes 30-60 seconds
- **Cached load**: Subsequent loads take 2-3 seconds
- **File retrieval**: Getting files for an experiment makes an additional API call (1-2 seconds per experiment)
- **Batch operations**: Cache experiments to ENCODE object to avoid redundant lookups

---

## Error Handling

```python
from encodeLib import encodeExperiment

try:
    exp = encodeExperiment('INVALID_ACCESSION')
except ValueError as e:
    print(f"Error: {e}")

# For experiments with no files:
exp = encodeExperiment('ENCSR000CDC')
files = exp.get_files_by_type()
if not files:
    print("No files found for this experiment")
```

---

## Experiment Metadata Caching

In addition to the main experiments list cache, individual experiment metadata can be cached for efficient retrieval. This is especially important when working with the ~27,000 experiments in the ENCODE database.

### Metadata Cache Architecture

The metadata cache uses a hierarchical directory structure to efficiently organize individual experiment data:

```
~/.encode_cache/
├── experiments.json                          # List of all experiments
└── metadata/
    ├── SR/                                   # Experiment type prefix (ENCSR...)
    │   ├── ENCSR000CDC.json
    │   ├── ENCSR000CNK.json
    │   └── ...
    ├── ER/                                   # (ENCER...)
    ├── DS/                                   # (ENCDS...)
    └── ... (other prefixes)
```

**Why hierarchical?** With 30,000 experiments, storing all metadata in a single directory could overwhelm the filesystem. This structure organizes files by experiment type prefix (the 2 characters after "ENC"), distributing them across directories.

### Automatic Metadata Caching

Individual experiment metadata is automatically cached when:
1. Loaded via API call from `encodeExperiment`
2. First accessed from the experiments list
3. Fetched using `_fetch_full_data()` for file information

```python
from encodeLib import ENCODE, encodeExperiment

encode = ENCODE(use_cache=True)

# First access - fetches from API and caches
exp1 = encode.getExperiment('ENCSR000CDC')

# Second access - loads from cache instantly
exp2 = encode.getExperiment('ENCSR000CDC')
```

### Metadata Cache Management

#### Get Cache Statistics

```python
stats = encode.get_metadata_cache_stats()
print(f"Cached experiments: {stats['total_cached_experiments']:,}")
print(f"Cache size: {stats['cache_size_mb']:.2f} MB")
print(f"Experiment types:")
for prefix in sorted(stats['type_prefixes'].keys()):
    count = stats['type_prefixes'][prefix]
    print(f"  {prefix}: {count:,} experiments")
```

#### Clear Metadata Cache

```python
# Clear cache for specific experiment
encode.clear_metadata_cache(accession='ENCSR000CDC')

# Clear all metadata cache
encode.clear_metadata_cache()
```

#### Refresh Experiment Data

```python
# Refresh a specific experiment
exp = encode.getExperiment('ENCSR000CDC')
exp.clear_cache(refresh=True)  # Fetch fresh from API and update cache

# Or just clear without refreshing
exp.clear_cache(refresh=False)
```

### Usage Examples

#### Example 1: Batch Processing with Metadata Caching

```python
from encodeLib import ENCODE

# Initialize with caching
encode = ENCODE(use_cache=True)

# Process many experiments
# First few fetch from API and cache, subsequent ones use cache
for i, exp_dict in enumerate(encode.experiments[:100]):
    accession = exp_dict['accession']
    exp = encode.getExperiment(accession)
    
    if i % 10 == 0:
        stats = encode.get_metadata_cache_stats()
        print(f"Progress: {i}/100, Cached: {stats['total_cached_experiments']}")
```

#### Example 2: Selective Cache Refresh

```python
# Load and work with experiment
exp = encode.getExperiment('ENCSR000CDC')
data1 = exp.get_all_metadata()

# Process data...

# Later, if you suspect the data changed, refresh it
exp.clear_cache(refresh=True)
data2 = exp.get_all_metadata()  # Fresh from API
```

#### Example 3: Monitor Cache Growth

```python
encode = ENCODE(use_cache=True)

# Track cache size
max_cache_size_mb = 1000

stats = encode.get_metadata_cache_stats()
print(f"Current cache: {stats['cache_size_mb']:.2f} MB")

if stats['cache_size_mb'] > max_cache_size_mb:
    print(f"Cache exceeded {max_cache_size_mb} MB, clearing...")
    encode.clear_metadata_cache()
    print("Cache cleared")
```

### ENCODE Methods for Metadata Cache

#### `_load_experiment_metadata(accession)`

Load experiment metadata from disk cache.

**Parameters:**
- `accession` (str): Experiment accession

**Returns:** Dictionary with experiment data, or `None` if not cached

#### `_save_experiment_metadata(accession, data)`

Save experiment metadata to disk cache.

**Parameters:**
- `accession` (str): Experiment accession
- `data` (dict): Experiment data to cache

#### `clear_metadata_cache(accession=None)`

Clear metadata cache for specific experiment or all experiments.

**Parameters:**
- `accession` (str, optional): Specific accession to clear. If `None`, clears all metadata cache.

**Example:**
```python
# Clear one experiment
encode.clear_metadata_cache('ENCSR000CDC')

# Clear all
encode.clear_metadata_cache()
```

#### `get_metadata_cache_stats()`

Get statistics about the metadata cache.

**Returns:** Dictionary with:
- `cache_dir` (str): Path to metadata cache directory
- `total_cached_experiments` (int): Number of cached files
- `cache_size_mb` (float): Total cache size in MB
- `cache_size_bytes` (int): Total cache size in bytes
- `type_prefixes` (dict): Count of cached experiments per type prefix

**Example:**
```python
stats = encode.get_metadata_cache_stats()
for prefix, count in stats['type_prefixes'].items():
    print(f"{prefix}: {count:,} experiments")
```

### encodeExperiment Methods for Cache Management

#### `clear_cache(refresh=False)`

Clear or refresh the cached metadata for this experiment.

**Parameters:**
- `refresh` (bool, optional): If `True`, fetch fresh data from API and update cache. If `False`, just clear cached data. Default: `False`

**Returns:** `True` if successful

**Example:**
```python
exp = encode.getExperiment('ENCSR000CDC')

# Clear cache without reloading
exp.clear_cache(refresh=False)

# Clear cache and reload fresh data from API
exp.clear_cache(refresh=True)
```

### Performance Characteristics

- **Cache hit**: < 5ms (loads JSON from disk)
- **Cache miss + API fetch**: 1-2 seconds per experiment
- **Batch operations**: First 100 experiments cache quickly, subsequent batches benefit from cache
- **Hierarchical organization**: Scales efficiently to 30,000+ experiments

### Tips and Best Practices

1. **Use the `getExperiment()` method** for cleaner syntax and automatic caching:
   ```python
   # Good - enables caching
   exp = encode.getExperiment('ENCSR000CDC')
   
   # Without caching (not recommended)
   exp = encodeExperiment('ENCSR000CDC')
   ```

2. **Check cache stats periodically** for batch operations:
   ```python
   stats = encode.get_metadata_cache_stats()
   print(f"Cached: {stats['total_cached_experiments']:,}")
   ```

3. **Clear cache if it grows too large**:
   ```python
   if encode.get_metadata_cache_stats()['cache_size_mb'] > 1000:
       encode.clear_metadata_cache()
   ```

4. **Use custom cache directory for isolated environments**:
   ```python
   encode = ENCODE(cache_dir='/tmp/encode_test_cache')
   ```


