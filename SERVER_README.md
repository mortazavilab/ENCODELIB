# ENCODE fastmcp Server

A fastmcp server exposing the ENCODE library functionality on `http://127.0.0.1:8080`.

## Features

- **Search experiments** by biosample or target
- **Retrieve experiment metadata** and file information
- **Organize files** by type, output category, or output type
- **Download files** automatically (with duplicate detection)
- **Local caching** for fast repeated access
- **Metadata caching** by experiment type prefix

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements-server.txt
```

### 2. Install fastmcp

The server uses `fastmcp` for MCP implementation:

```bash
pip install fastmcp
```

## Running the Server

### Option 1: Using the startup script (recommended)

```bash
chmod +x start-server.sh
./start-server.sh
```

### Option 2: Direct Python execution

```bash
python3 encode_server.py
```

### Option 3: Using fastmcp CLI

```bash
fastmcp run encode_server.py
```

The server will start on `http://127.0.0.1:8080`.

## Directory Structure

```
.
├── encode_server.py              # Main server script
├── requirements-server.txt       # Python dependencies
├── start-server.sh              # Startup script
├── .encode_cache/               # Experiment cache (auto-created)
│   ├── experiments.json         # List of all experiments
│   └── metadata/                # Individual experiment metadata
│       ├── SR/                  # ENCSR experiments
│       ├── ER/                  # ENCER experiments
│       └── ...
└── files/                       # Downloaded files (auto-created)
    ├── ENCSR000CDC/
    ├── ENCSR123ABC/
    └── ...
```

## Available Tools

### Search Tools

#### `search_by_biosample`
Search for experiments by cell type, tissue name, or biosample.

**Parameters:**
- `search_term` (str, required): Cell type or tissue (e.g., 'K562', 'heart', 'GM12878')
- `organism` (str, optional): Filter by organism (e.g., 'Homo sapiens')
- `assay_title` (str, optional): Filter by assay type (e.g., 'TF ChIP-seq')
- `target` (str, optional): Filter by target name
- `exclude_revoked` (bool, default: True): Exclude revoked experiments

**Returns:** List of experiment objects with metadata

**Example:**
```json
{
  "search_term": "K562",
  "organism": "Homo sapiens",
  "assay_title": "TF ChIP-seq"
}
```

#### `search_by_target`
Search for experiments by transcription factor or histone mark target.

**Parameters:**
- `target` (str, required): Target name (e.g., 'TP53', 'H3K27ac', 'CTCF')
- `organism` (str, optional): Filter by organism
- `assay_title` (str, optional): Filter by assay type
- `exclude_revoked` (bool, default: True): Exclude revoked experiments

**Returns:** List of experiment objects with metadata

**Example:**
```json
{
  "target": "TP53",
  "organism": "Homo sapiens"
}
```

### Experiment Tools

#### `get_experiment`
Get detailed metadata for a specific experiment.

**Parameters:**
- `accession` (str, required): ENCODE experiment accession (e.g., 'ENCSR000CDC')

**Returns:** Experiment metadata dictionary

#### `get_all_metadata`
Get all available metadata from the ENCODE API for an experiment.

**Parameters:**
- `accession` (str, required): ENCODE experiment accession

**Returns:** Complete raw metadata dictionary from ENCODE API

### File Discovery Tools

#### `get_file_types`
Get available file types in an experiment.

**Parameters:**
- `accession` (str, required): Experiment accession

**Returns:** List of file types (e.g., `['bam', 'fastq', 'bigWig']`)

#### `get_files_by_type`
Get all files organized by file type with comprehensive metadata.

**Parameters:**
- `accession` (str, required): Experiment accession
- `after_date` (str, optional): Date filter (YYYY-MM-DD)
- `file_status` (str, default: 'released'): File status filter

**Returns:** Dictionary with file type as key and list of file metadata as values

#### `get_file_accessions_by_type`
Get file accessions organized by file type.

**Parameters:**
- `accession` (str, required): Experiment accession
- `after_date` (str, optional): Date filter
- `file_types` (list[str], optional): Specific file types to include

**Returns:** Dictionary with file type as key and list of accessions as values

#### `get_available_output_categories`
Get available output categories (e.g., 'raw data', 'processed data').

**Parameters:**
- `accession` (str, required): Experiment accession

**Returns:** List of output categories

#### `get_available_output_types`
Get available output types (e.g., 'reads', 'alignments', 'peaks').

**Parameters:**
- `accession` (str, required): Experiment accession

**Returns:** List of output types

#### `get_file_accessions_by_output_category`
Get file accessions organized by output category.

**Parameters:**
- `accession` (str, required): Experiment accession
- `output_categories` (list[str], optional): Categories to filter by

**Returns:** Dictionary with category as key and list of accessions as values

#### `get_file_accessions_by_output_type`
Get file accessions organized by output type.

**Parameters:**
- `accession` (str, required): Experiment accession
- `output_types` (list[str], optional): Output types to filter by

**Returns:** Dictionary with output type as key and list of accessions as values

#### `get_files_summary`
Get summary view of files by type.

**Parameters:**
- `accession` (str, required): Experiment accession
- `max_files_per_type` (int, optional): Maximum files to show per type

**Returns:** Dictionary with file type summary

### File Metadata Tools

#### `get_file_metadata`
Get comprehensive metadata for a specific file.

**Parameters:**
- `accession` (str, required): Experiment accession
- `file_accession` (str, required): File accession ID

**Returns:** Complete file metadata dictionary

#### `get_file_url`
Get download URL for a specific file.

**Parameters:**
- `accession` (str, required): Experiment accession
- `file_accession` (str, required): File accession ID

**Returns:** Dictionary with download URL

### Download Tools

#### `download_files`
Download files from an experiment to `./files/{accession}/`

**Parameters:**
- `accession` (str, required): Experiment accession
- `file_types` (list[str], optional): Specific file types to download
- `file_accessions` (list[str], optional): Specific file accessions to download

**Returns:** Download result with lists of downloaded, failed, and skipped files

**Example:**
```json
{
  "accession": "ENCSR000CDC",
  "file_types": ["fastq", "bam"]
}
```

### Cache Management Tools

#### `get_cache_stats`
Get statistics about the metadata cache.

**Returns:** Dictionary with cache statistics including:
- `cache_dir`: Path to cache directory
- `total_cached_experiments`: Number of cached experiment metadata files
- `cache_size_mb`: Total cache size in MB
- `type_prefixes`: Count of cached experiments per type prefix

#### `clear_cache`
Clear caches.

**Parameters:**
- `clear_metadata` (bool, default: False): If True, also clear metadata cache

**Returns:** Confirmation message

### Utility Tools

#### `list_experiments`
List loaded experiments with pagination.

**Parameters:**
- `limit` (int, default: 100): Maximum experiments to return
- `offset` (int, default: 0): Starting index

**Returns:** Dictionary with experiment list and pagination info

#### `get_server_info`
Get server configuration information.

**Returns:** Dictionary with server settings

## Resources

The server also exposes resources:

- `cache://stats`: Get cache statistics
- `server://info`: Get server information

## Usage Examples

### Search for experiments

```
Tool: search_by_biosample
Parameters:
  search_term: "K562"
  organism: "Homo sapiens"
  assay_title: "TF ChIP-seq"
```

### Get experiment files

```
Tool: get_file_accessions_by_type
Parameters:
  accession: "ENCSR000CDC"
  file_types: ["fastq", "bam"]
```

### Download specific file types

```
Tool: download_files
Parameters:
  accession: "ENCSR000CDC"
  file_types: ["fastq"]
```

### Check cache status

```
Tool: get_cache_stats
```

## Caching Behavior

The server automatically uses two levels of caching:

1. **Experiments List Cache** (`.encode_cache/experiments.json`)
   - Caches the list of all ~27,000 ENCODE experiments
   - Updated on first run or with force refresh

2. **Metadata Cache** (`.encode_cache/metadata/{type}/{accession}.json`)
   - Hierarchically organized by experiment type prefix
   - Caches individual experiment metadata and file information
   - Auto-populated as experiments are accessed

## Performance Notes

- **First startup**: 30-60 seconds (downloads ~27,000 experiments)
- **Subsequent startups**: 2-3 seconds (loads from cache)
- **Per-experiment metadata**: 1-2 seconds on first access, instant on cache hit
- **File downloads**: Depends on network and file size; automatically skips duplicates

## Troubleshooting

### Server won't start

1. Check Python version (requires 3.8+)
   ```bash
   python3 --version
   ```

2. Install dependencies
   ```bash
   pip install -r requirements-server.txt
   ```

3. Check if port 8080 is available
   ```bash
   lsof -i :8080
   ```

### Cache is too large

Clear the metadata cache:
```json
Tool: clear_cache
Parameters:
  clear_metadata: true
```

### Slow performance

1. Check cache stats:
   ```json
   Tool: get_cache_stats
   ```

2. Clear old cache if needed:
   ```json
   Tool: clear_cache
   Parameters:
     clear_metadata: true
   ```

## Development

To add new tools to the server, use the `@server.tool()` decorator:

```python
@server.tool()
def my_tool(param1: str, param2: int = 10) -> dict:
    """
    Tool description.
    
    Args:
        param1: Parameter description
        param2: Optional parameter
    
    Returns:
        Result description
    """
    # Implementation here
    return {"result": value}
```

## License

Same as ENCODE library
