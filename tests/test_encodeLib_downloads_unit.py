"""Focused unit tests for encodeExperiment download enhancements."""

from __future__ import annotations

import importlib
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


class TestEncodeExperimentDownloads(unittest.TestCase):
    """Verify additive preview/resume/checksum behavior."""

    def setUp(self):
        self.encode_lib = load_encode_lib_module()
        self.experiment = self.encode_lib.encodeExperiment(
            experiment_data={
                "accession": "ENCSR000TEST",
                "files": [
                    {
                        "accession": "ENCFF001ABC",
                        "file_type": "fastq",
                        "file_format": "fastq",
                        "filename": "file.fastq.gz",
                        "href": "/files/ENCFF001ABC/@@download/file.fastq.gz",
                        "md5sum": "deadbeef",
                        "status": "released",
                    }
                ],
            }
        )

    def test_preview_only_returns_manifest(self):
        result = self.experiment.download_files("/tmp/encode-preview", preview_only=True)

        self.assertEqual(result["downloaded"], [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(len(result["manifest"]), 1)
        self.assertEqual(result["manifest"][0]["accession"], "ENCFF001ABC")

    def test_checksum_mismatch_fails_download(self):
        class DummyResponse:
            status_code = 200

            def iter_content(self, chunk_size=8192):
                yield b"test-bytes"

        with patch.object(self.encode_lib, "_request_with_retry", return_value=DummyResponse()):
            with tempfile.TemporaryDirectory() as tmpdir:
                result = self.experiment.download_files(tmpdir, verify_checksum=True)

                self.assertEqual(len(result["failed"]), 1)
                self.assertEqual(result["failed"][0][0], "ENCFF001ABC")
                self.assertFalse((Path(tmpdir) / "file.fastq.gz").exists())

    def test_resume_passes_range_header_for_partial_temp_file(self):
        request_headers = []

        class DummyResponse:
            status_code = 206

            def iter_content(self, chunk_size=8192):
                yield b"-suffix"

        def _request(*args, **kwargs):
            request_headers.append(kwargs.get("headers"))
            return DummyResponse()

        with patch.object(self.encode_lib, "_request_with_retry", side_effect=_request):
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_path = Path(tmpdir) / "file.fastq.gz.tmp"
                temp_path.write_bytes(b"prefix")
                result = self.experiment.download_files(tmpdir, resume=True)

                self.assertEqual(result["downloaded"], ["ENCFF001ABC"])
                self.assertEqual(request_headers[0], {"Range": "bytes=6-"})
                self.assertEqual((Path(tmpdir) / "file.fastq.gz").read_bytes(), b"prefix-suffix")


if __name__ == "__main__":
    unittest.main()