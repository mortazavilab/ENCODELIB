"""
Unit tests for encodeLib.py core library functionality.

Tests cover:
- ENCODE class initialization and caching
- Experiment search methods
- encodeExperiment class
- File discovery and filtering
- Error handling
- Cache management
"""

import unittest
import tempfile
import shutil
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from encodeLib import ENCODE, encodeExperiment


class TestENCODEInitialization(unittest.TestCase):
    """Test ENCODE class initialization and basic setup."""
    
    def setUp(self):
        """Set up temporary cache directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / "test_cache"
    
    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @patch('encodeLib.requests.get')
    def test_initialization_with_custom_cache(self, mock_get):
        """Test ENCODE initialization with custom cache directory."""
        # Mock the API response
        mock_response = Mock()
        mock_response.json.return_value = {'@graph': []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        encode = ENCODE(use_cache=False, cache_dir=str(self.cache_dir))
        
        self.assertEqual(encode.cache_dir, self.cache_dir)
        self.assertEqual(len(encode.experiments), 0)
        mock_get.assert_called_once()
    
    @patch('encodeLib.requests.get')
    def test_cache_loading(self, mock_get):
        """Test loading experiments from cache."""
        # Create a cache file
        cache_file = self.cache_dir / "experiments.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        test_experiments = [
            {'accession': 'ENCSR000CDC', 'status': 'released'},
            {'accession': 'ENCSR000AAA', 'status': 'released'}
        ]
        
        with open(cache_file, 'w') as f:
            json.dump({'experiments': test_experiments}, f)
        
        # Initialize ENCODE with cache
        encode = ENCODE(use_cache=True, cache_dir=str(self.cache_dir))
        
        # Should load from cache without calling API
        mock_get.assert_not_called()
        self.assertEqual(len(encode.experiments), 2)
        self.assertEqual(encode.experiments[0]['accession'], 'ENCSR000CDC')
    
    @patch('encodeLib.requests.get')
    def test_force_refresh(self, mock_get):
        """Test force refresh ignores cache."""
        # Create a cache file
        cache_file = self.cache_dir / "experiments.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump({'experiments': [{'accession': 'OLD'}]}, f)
        
        # Mock API response with different data
        mock_response = Mock()
        mock_response.json.return_value = {'@graph': [{'accession': 'NEW'}]}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        encode = ENCODE(use_cache=True, force_refresh=True, cache_dir=str(self.cache_dir))
        
        # Should call API despite cache existing
        mock_get.assert_called_once()
        self.assertEqual(encode.experiments[0]['accession'], 'NEW')


class TestENCODESearchMethods(unittest.TestCase):
    """Test experiment search methods."""
    
    def setUp(self):
        """Set up test data."""
        self.test_experiments = [
            {
                'accession': 'ENCSR000CDC',
                'status': 'released',
                'biosample_summary': 'K562',
                'assay_title': 'TF ChIP-seq',
                'target': {'label': 'CTCF'},
                'replicates': [{
                    'library': {
                        'biosample': {
                            'organism': {'scientific_name': 'Homo sapiens'}
                        }
                    }
                }]
            },
            {
                'accession': 'ENCSR000AAA',
                'status': 'released',
                'biosample_summary': 'GM12878',
                'assay_title': 'RNA-seq',
                'replicates': [{
                    'library': {
                        'biosample': {
                            'organism': {'scientific_name': 'Homo sapiens'}
                        }
                    }
                }]
            },
            {
                'accession': 'ENCSR000BBB',
                'status': 'revoked',
                'biosample_summary': 'K562',
                'assay_title': 'TF ChIP-seq',
                'target': {'label': 'TP53'},
                'replicates': [{
                    'library': {
                        'biosample': {
                            'organism': {'scientific_name': 'Homo sapiens'}
                        }
                    }
                }]
            },
            {
                'accession': 'ENCSR000DDD',
                'status': 'released',
                'biosample_summary': 'liver',
                'assay_title': 'RNA-seq',
                'replicates': [{
                    'library': {
                        'biosample': {
                            'organism': {'scientific_name': 'Mus musculus'}
                        }
                    }
                }]
            }
        ]
    
    def _create_mock_encode(self):
        """Create a mock ENCODE instance with test data."""
        with patch('encodeLib.requests.get'):
            encode = ENCODE.__new__(ENCODE)
            encode.experiments = self.test_experiments
            encode.base_url = "https://www.encodeproject.org"
            return encode
    
    def test_search_by_biosample(self):
        """Test searching experiments by biosample."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_biosample(
            'K562', 
            organism='Homo sapiens',
            return_objects=False
        )
        
        # Should find 1 released K562 experiment (excludes revoked by default)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['accession'], 'ENCSR000CDC')
    
    def test_search_by_biosample_case_insensitive(self):
        """Test biosample search is case-insensitive."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_biosample(
            'k562',  # lowercase
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['accession'], 'ENCSR000CDC')
    
    def test_search_by_biosample_with_assay_filter(self):
        """Test biosample search with assay filtering."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_biosample(
            'K562',
            assay_title='TF ChIP-seq',
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['assay_title'], 'TF ChIP-seq')
    
    def test_search_by_biosample_assay_case_insensitive(self):
        """Test assay filtering is case-insensitive."""
        encode = self._create_mock_encode()
        
        # Test with different case
        results = encode.search_experiments_by_biosample(
            'K562',
            assay_title='tf chip-seq',  # lowercase
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
    
    def test_search_by_target(self):
        """Test searching by target."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_target(
            'CTCF',
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['accession'], 'ENCSR000CDC')
    
    def test_search_by_target_partial_match(self):
        """Test target search supports partial matching."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_target(
            'CT',  # Partial match for CTCF
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
    
    def test_search_by_target_assay_case_insensitive(self):
        """Test target search has case-insensitive assay filtering."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_target(
            'CTCF',
            assay_title='TF ChIP-seq',
            return_objects=False
        )
        self.assertEqual(len(results), 1)
        
        # Test with different case
        results_lower = encode.search_experiments_by_target(
            'CTCF',
            assay_title='tf chip-seq',  # lowercase
            return_objects=False
        )
        self.assertEqual(len(results_lower), 1)
    
    def test_exclude_revoked_default(self):
        """Test that revoked experiments are excluded by default."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_biosample(
            'K562',
            return_objects=False
        )
        
        # Should only get the released experiment, not the revoked one
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['status'], 'released')
    
    def test_include_revoked(self):
        """Test including revoked experiments."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_biosample(
            'K562',
            exclude_revoked=False,
            return_objects=False
        )
        
        # Should get both released and revoked
        self.assertEqual(len(results), 2)
    
    def test_search_by_organism(self):
        """Test searching by organism."""
        encode = self._create_mock_encode()
        
        results = encode.search_experiments_by_organism(
            'Mus musculus',
            return_objects=False
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['accession'], 'ENCSR000DDD')


class TestEncodeExperiment(unittest.TestCase):
    """Test encodeExperiment class functionality."""
    
    def setUp(self):
        """Set up test experiment data."""
        self.test_exp_data = {
            'accession': 'ENCSR000TEST',
            'status': 'released',
            'biosample_summary': 'K562',
            'assay_title': 'TF ChIP-seq',
            'description': 'Test experiment',
            'target': {'label': 'CTCF'},
            'lab': {'title': 'Test Lab'},
            'replicates': [
                {
                    'library': {
                        'biosample': {
                            'organism': {'scientific_name': 'Homo sapiens'}
                        }
                    }
                },
                {}  # Second replicate
            ],
            'files': [
                {
                    'accession': 'ENCFF001AAA',
                    'file_type': 'fastq',
                    'status': 'released',
                    'output_type': 'reads',
                    'output_category': 'raw data',
                    'filename': 'test.fastq.gz',
                    'href': '/files/ENCFF001AAA/@@download/test.fastq.gz'
                },
                {
                    'accession': 'ENCFF001BBB',
                    'file_type': 'bam',
                    'status': 'released',
                    'output_type': 'alignments',
                    'output_category': 'processed data',
                    'filename': 'test.bam',
                    'href': '/files/ENCFF001BBB/@@download/test.bam'
                }
            ]
        }
    
    def test_initialization_with_data(self):
        """Test initializing encodeExperiment with full data."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        self.assertEqual(exp.accession, 'ENCSR000TEST')
        self.assertEqual(exp.organism, 'Homo sapiens')
        self.assertEqual(exp.assay, 'TF ChIP-seq')
        self.assertEqual(exp.biosample, 'K562')
        self.assertEqual(exp.replicate_count, 2)
        self.assertEqual(exp.targets, ['CTCF'])
    
    def test_get_file_types(self):
        """Test getting available file types."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        file_types = exp.get_file_types()
        
        self.assertEqual(sorted(file_types), ['bam', 'fastq'])
    
    def test_get_files_by_type(self):
        """Test organizing files by type."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        files_by_type = exp.get_files_by_type()
        
        self.assertIn('fastq', files_by_type)
        self.assertIn('bam', files_by_type)
        self.assertEqual(len(files_by_type['fastq']), 1)
        self.assertEqual(files_by_type['fastq'][0]['accession'], 'ENCFF001AAA')
    
    def test_get_files_by_type_caching(self):
        """Test that get_files_by_type caches results."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        # First call
        files1 = exp.get_files_by_type()
        # Second call should return cached result
        files2 = exp.get_files_by_type()
        
        # Should be the same object (cached)
        self.assertIs(files1, files2)
    
    def test_get_available_output_categories(self):
        """Test getting output categories."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        categories = exp.get_available_output_categories()
        
        self.assertIn('raw data', categories)
        self.assertIn('processed data', categories)
    
    def test_get_available_output_types(self):
        """Test getting output types."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        output_types = exp.get_available_output_types()
        
        self.assertIn('reads', output_types)
        self.assertIn('alignments', output_types)
    
    def test_get_file_metadata(self):
        """Test getting metadata for specific file."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        metadata = exp.get_file_metadata('ENCFF001AAA')
        
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata['file_type'], 'fastq')
        self.assertEqual(metadata['output_type'], 'reads')
    
    def test_get_file_url(self):
        """Test getting file download URL."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        url = exp.get_file_url('ENCFF001AAA')
        
        self.assertIn('encodeproject.org', url)
        self.assertIn('ENCFF001AAA', url)
    
    def test_to_dict(self):
        """Test converting experiment to dictionary."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        exp_dict = exp.to_dict()
        
        self.assertEqual(exp_dict['Accession'], 'ENCSR000TEST')
        self.assertEqual(exp_dict['Organism'], 'Homo sapiens')
        self.assertEqual(exp_dict['Assay'], 'TF ChIP-seq')


class TestFileDiscovery(unittest.TestCase):
    """Test file discovery and filtering methods."""
    
    def setUp(self):
        """Set up test data with various file types."""
        self.test_exp_data = {
            'accession': 'ENCSR000TEST',
            'files': [
                {
                    'accession': 'ENCFF001',
                    'file_type': 'fastq',
                    'status': 'released',
                    'output_type': 'reads',
                    'output_category': 'raw data'
                },
                {
                    'accession': 'ENCFF002',
                    'file_type': 'fastq',
                    'status': 'released',
                    'output_type': 'reads',
                    'output_category': 'raw data'
                },
                {
                    'accession': 'ENCFF003',
                    'file_type': 'bam',
                    'status': 'released',
                    'output_type': 'alignments',
                    'output_category': 'processed data'
                },
                {
                    'accession': 'ENCFF004',
                    'file_type': 'bam',
                    'status': 'archived',
                    'output_type': 'alignments',
                    'output_category': 'processed data'
                }
            ]
        }
    
    def test_get_file_accessions_by_type(self):
        """Test getting file accessions organized by type."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        accessions = exp.get_file_accessions_by_type()
        
        self.assertEqual(len(accessions['fastq']), 2)
        self.assertEqual(len(accessions['bam']), 1)  # Only released
        self.assertIn('ENCFF001', accessions['fastq'])
    
    def test_get_file_accessions_by_type_filtered(self):
        """Test filtering by specific file types."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        accessions = exp.get_file_accessions_by_type(file_types=['fastq'])
        
        self.assertIn('fastq', accessions)
        self.assertNotIn('bam', accessions)
    
    def test_get_file_accessions_by_output_category(self):
        """Test organizing files by output category."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        by_category = exp.get_file_accessions_by_output_category()
        
        self.assertEqual(len(by_category['raw data']), 2)
        self.assertEqual(len(by_category['processed data']), 1)
    
    def test_get_file_accessions_by_output_type(self):
        """Test organizing files by output type."""
        exp = encodeExperiment(experiment_data=self.test_exp_data)
        
        by_type = exp.get_file_accessions_by_output_type()
        
        self.assertEqual(len(by_type['reads']), 2)
        self.assertEqual(len(by_type['alignments']), 1)


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases."""
    
    @patch('encodeLib.requests.get')
    def test_api_error_handling(self, mock_get):
        """Test proper error handling for API failures."""
        # Mock a failed API response
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_get.return_value = mock_response
        
        with self.assertRaises(Exception):
            ENCODE(use_cache=False)
    
    def test_invalid_accession_format(self):
        """Test handling of invalid accession format."""
        encode = ENCODE.__new__(ENCODE)
        encode.metadata_cache_dir = Path("/tmp/test_cache")
        
        with self.assertRaises(ValueError):
            encode._get_metadata_cache_path("INVALID")
    
    def test_missing_experiment_data(self):
        """Test handling missing experiment data fields."""
        minimal_data = {'accession': 'ENCSR000MIN'}
        exp = encodeExperiment(experiment_data=minimal_data)
        
        # Should handle missing fields gracefully
        self.assertEqual(exp.accession, 'ENCSR000MIN')
        self.assertEqual(exp.targets, [])
        self.assertEqual(exp.replicate_count, 0)


class TestCacheManagement(unittest.TestCase):
    """Test cache management functionality."""
    
    def setUp(self):
        """Set up temporary cache directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.cache_dir = Path(self.temp_dir) / "cache"
    
    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @patch('encodeLib.requests.get')
    def test_metadata_cache_path_structure(self, mock_get):
        """Test hierarchical metadata cache structure."""
        mock_response = Mock()
        mock_response.json.return_value = {'@graph': []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        encode = ENCODE(use_cache=False, cache_dir=str(self.cache_dir))
        
        cache_path = encode._get_metadata_cache_path('ENCSR000CDC')
        
        # Should be in SR subdirectory
        self.assertIn('/SR/', str(cache_path))
        self.assertTrue(str(cache_path).endswith('ENCSR000CDC.json'))
    
    @patch('encodeLib.requests.get')
    def test_save_and_load_metadata(self, mock_get):
        """Test saving and loading experiment metadata."""
        mock_response = Mock()
        mock_response.json.return_value = {'@graph': []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        encode = ENCODE(use_cache=True, cache_dir=str(self.cache_dir))
        
        test_data = {'accession': 'ENCSR000CDC', 'status': 'released'}
        encode._save_experiment_metadata('ENCSR000CDC', test_data)
        
        loaded = encode._load_experiment_metadata('ENCSR000CDC')
        
        self.assertEqual(loaded['accession'], 'ENCSR000CDC')
    
    @patch('encodeLib.requests.get')
    def test_cache_stats(self, mock_get):
        """Test getting cache statistics."""
        mock_response = Mock()
        mock_response.json.return_value = {'@graph': []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        encode = ENCODE(use_cache=True, cache_dir=str(self.cache_dir))
        
        # Save some metadata
        encode._save_experiment_metadata('ENCSR000AAA', {'data': 'test1'})
        encode._save_experiment_metadata('ENCSR000BBB', {'data': 'test2'})
        encode._save_experiment_metadata('ENCER000CCC', {'data': 'test3'})
        
        stats = encode.get_metadata_cache_stats()
        
        self.assertEqual(stats['total_cached_experiments'], 3)
        self.assertIn('SR', stats['type_prefixes'])
        self.assertIn('ER', stats['type_prefixes'])
        self.assertEqual(stats['type_prefixes']['SR'], 2)
        self.assertEqual(stats['type_prefixes']['ER'], 1)


class TestFileDownloadSecurity(unittest.TestCase):
    """Test file download security measures."""
    
    def test_filename_sanitization(self):
        """Test that filenames are sanitized to prevent path traversal."""
        test_exp_data = {
            'accession': 'ENCSR000TEST',
            'files': [
                {
                    'accession': 'ENCFF001',
                    'file_type': 'fastq',
                    'status': 'released',
                    'filename': '../../../etc/passwd',  # Path traversal attempt
                    'href': '/files/ENCFF001/@@download/file.fastq.gz'
                },
                {
                    'accession': 'ENCFF002',
                    'file_type': 'fastq',
                    'status': 'released',
                    'filename': '.hidden',  # Hidden file
                    'href': '/files/ENCFF002/@@download/file.fastq.gz'
                }
            ]
        }
        
        exp = encodeExperiment(experiment_data=test_exp_data)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('encodeLib.requests.get') as mock_get:
                # Mock successful download response
                mock_response = Mock()
                mock_response.raise_for_status.return_value = None
                mock_response.iter_content.return_value = [b'test']
                mock_get.return_value = mock_response
                
                result = exp.download_files(tmpdir)
                
                # Path traversal file should fail
                self.assertIn('ENCFF001', [acc for acc, _ in result['failed']])
                # Hidden file should fail
                self.assertIn('ENCFF002', [acc for acc, _ in result['failed']])


if __name__ == '__main__':
    unittest.main()
