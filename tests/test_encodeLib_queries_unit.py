"""Focused unit tests for v0.4 ENCODE query helpers."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_encode_lib_module():
    """Load encodeLib with lightweight dependency shims."""
    fake_pandas = types.ModuleType("pandas")
    fake_pandas.DataFrame = type("DummyDataFrame", (), {})

    fake_requests = types.ModuleType("requests")
    request_error = type("RequestError", (Exception,), {})
    fake_requests.exceptions = types.SimpleNamespace(
        ConnectionError=request_error,
        Timeout=request_error,
        HTTPError=request_error,
    )
    fake_requests.Response = type("Response", (), {})
    fake_requests.get = lambda *args, **kwargs: None

    with patch.dict(
        sys.modules,
        {
            "pandas": fake_pandas,
            "requests": fake_requests,
        },
        clear=False,
    ):
        sys.modules.pop("encodeLib", None)
        return importlib.import_module("encodeLib")


class TestEncodeQueryHelpers(unittest.TestCase):
    """Verify additive batch, facet, export, and metrics helpers."""

    def setUp(self):
        self.encode_lib = load_encode_lib_module()
        self.encode = self.encode_lib.ENCODE.__new__(self.encode_lib.ENCODE)
        self.encode.load_mode = "incremental"
        self.encode._experiments_loaded = False
        self.encode._experiments = []
        self.encode._search_index = None
        self.encode._incremental_offset = 0
        self.encode._instance_metrics = {
            "summary_cache_hits": 0,
            "summary_cache_misses": 0,
            "metadata_cache_hits": 0,
            "metadata_cache_misses": 0,
            "search_calls": 0,
            "batch_search_calls": 0,
            "exports": 0,
        }
        self.encode._experiment_summaries = [
            {
                "accession": "ENCSR000CDC",
                "status": "released",
                "biosample_summary": "K562",
                "biosample_ontology": {"term_name": "K562"},
                "assay_title": "TF ChIP-seq",
                "target": {"label": "CTCF"},
                "organism": "Homo sapiens",
                "lab": {"title": "Test Lab"},
                "description": "summary",
                "replicates": [{"library": {"biosample": {"organism": {"scientific_name": "Homo sapiens"}}}}],
                "@id": "/experiments/ENCSR000CDC/",
            },
            {
                "accession": "ENCSR000AAA",
                "status": "released",
                "biosample_summary": "GM12878",
                "biosample_ontology": {"term_name": "GM12878"},
                "assay_title": "RNA-seq",
                "target": None,
                "organism": "Homo sapiens",
                "lab": {"title": "Test Lab"},
                "description": "summary",
                "replicates": [{"library": {"biosample": {"organism": {"scientific_name": "Homo sapiens"}}}}],
                "@id": "/experiments/ENCSR000AAA/",
            },
        ]
        self.encode._summary_lookup = {
            exp["accession"]: exp for exp in self.encode._experiment_summaries
        }

    def test_search_experiments_batch_returns_named_results(self):
        results = self.encode.search_experiments_batch(
            [
                {"name": "k562", "mode": "biosample", "value": "K562"},
                {"name": "ctcf", "mode": "target", "value": "CTCF"},
            ],
            return_objects=False,
        )

        self.assertEqual(results["k562"][0]["accession"], "ENCSR000CDC")
        self.assertEqual(results["ctcf"][0]["accession"], "ENCSR000CDC")

    def test_get_experiment_facets_counts_expected_values(self):
        facets = self.encode.get_experiment_facets(fields=["assay_title", "organism", "target"])

        self.assertEqual(facets["assay_title"]["TF ChIP-seq"], 1)
        self.assertEqual(facets["organism"]["Homo sapiens"], 2)
        self.assertEqual(facets["target"]["CTCF"], 1)

    def test_export_experiments_writes_json_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "experiments.json"
            written_path = self.encode.export_experiments(str(output_path), experiments=[], format="json")

            self.assertEqual(written_path, output_path)
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload, [])

    def test_get_performance_stats_reports_search_index(self):
        self.encode.build_search_index()
        stats = self.encode.get_performance_stats()

        self.assertEqual(stats["load_mode"], "incremental")
        self.assertTrue(stats["search_index"]["built"])


if __name__ == "__main__":
    unittest.main()