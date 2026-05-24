"""Focused unit tests for ENCODE lazy-loading behavior."""

from __future__ import annotations

import importlib
import sys
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


class TestEncodeLazyLoading(unittest.TestCase):
    """Verify lazy loading is opt-in and preserves direct accession access."""

    def test_invalid_load_mode_raises(self):
        encode_lib = load_encode_lib_module()

        with self.assertRaises(ValueError):
            encode_lib.ENCODE(load_mode="invalid")

    def test_incremental_mode_loads_summaries_without_full_experiments(self):
        encode_lib = load_encode_lib_module()

        summary_payload = [
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
                "replicates": [],
                "@id": "/experiments/ENCSR000CDC/",
            }
        ]

        with patch.object(encode_lib.ENCODE, "load_experiment_summaries", autospec=True) as mock_load_summaries:
            def _side_effect(self, force_refresh=False):
                self._set_experiment_summaries(summary_payload)
                return summary_payload

            mock_load_summaries.side_effect = _side_effect
            encode = encode_lib.ENCODE(use_cache=False, load_mode="incremental")

        self.assertEqual(encode.load_mode, "incremental")
        self.assertFalse(encode._experiments_loaded)
        self.assertEqual(encode.get_experiment_summaries()[0]["accession"], "ENCSR000CDC")

    def test_build_search_index_supports_indexed_search(self):
        encode_lib = load_encode_lib_module()
        encode = encode_lib.ENCODE.__new__(encode_lib.ENCODE)
        encode.load_mode = "incremental"
        encode._experiments_loaded = False
        encode._experiments = []
        encode._search_index = None
        encode._incremental_offset = 0
        encode._instance_metrics = {
            "summary_cache_hits": 0,
            "summary_cache_misses": 0,
            "metadata_cache_hits": 0,
            "metadata_cache_misses": 0,
            "search_calls": 0,
            "batch_search_calls": 0,
            "exports": 0,
        }
        encode._experiment_summaries = [
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
                "replicates": [],
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
                "replicates": [],
                "@id": "/experiments/ENCSR000AAA/",
            },
        ]
        encode._summary_lookup = {
            exp["accession"]: exp for exp in encode._experiment_summaries
        }
        encode.create_experiment_object = lambda exp: exp

        encode.build_search_index()
        results = encode.search_experiments_by_biosample("K562", organism="Homo sapiens", return_objects=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["accession"], "ENCSR000CDC")

    def test_lazy_mode_defers_experiment_list_loading(self):
        encode_lib = load_encode_lib_module()
        load_calls = []

        with patch.object(
            encode_lib.ENCODE,
            "_load_experiments",
            side_effect=lambda self=None: load_calls.append("load") or [{"accession": "ENCSR000CDC"}],
        ):
            encode = encode_lib.ENCODE(use_cache=False, load_mode="lazy")

            self.assertEqual(load_calls, [])
            self.assertFalse(encode._experiments_loaded)

            experiments = encode.experiments

            self.assertEqual(load_calls, ["load"])
            self.assertTrue(encode._experiments_loaded)
            self.assertEqual(experiments[0]["accession"], "ENCSR000CDC")

    def test_get_experiment_does_not_force_full_list_load(self):
        encode_lib = load_encode_lib_module()
        load_calls = []

        with patch.object(
            encode_lib.ENCODE,
            "_load_experiments",
            side_effect=lambda self=None: load_calls.append("load") or [],
        ):
            fake_response = type(
                "DummyResponse",
                (),
                {"json": lambda self: {"accession": "ENCSR000XYZ", "status": "released"}},
            )()

            with patch.object(encode_lib, "_request_with_retry", return_value=fake_response):
                encode = encode_lib.ENCODE(use_cache=False, load_mode="lazy")
                experiment = encode.getExperiment("ENCSR000XYZ")

            self.assertEqual(experiment.accession, "ENCSR000XYZ")
            self.assertEqual(load_calls, [])


if __name__ == "__main__":
    unittest.main()