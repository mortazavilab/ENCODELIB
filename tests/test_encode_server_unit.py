"""Focused unit tests for encode_server.py behavior.

These tests avoid a real fastmcp server and heavy optional dependencies by
loading the module with lightweight import shims.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_encode_server_module():
    """Load encode_server with lightweight dependency shims."""
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

    fake_fastmcp = types.ModuleType("fastmcp")

    class DummyFastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self, *args, **kwargs):
            raise AssertionError("run() should not be called in unit tests")

    fake_fastmcp.FastMCP = DummyFastMCP

    with patch.dict(
        sys.modules,
        {
            "pandas": fake_pandas,
            "requests": fake_requests,
            "fastmcp": fake_fastmcp,
        },
        clear=False,
    ):
        sys.modules.pop("encode_server", None)
        sys.modules.pop("encodeLib", None)
        return importlib.import_module("encode_server")


class TestEncodeServerAuth(unittest.TestCase):
    """Verify auth enforcement is wired into MCP tool handlers."""

    def test_all_tools_accept_api_key_and_check_it_early(self):
        source = (ROOT_DIR / "encode_server.py").read_text()
        module = ast.parse(source)

        tool_functions = []
        for node in module.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            is_tool = any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "server"
                and dec.func.attr == "tool"
                for dec in node.decorator_list
            )
            if not is_tool:
                continue
            tool_functions.append(node.name)

            arg_names = [arg.arg for arg in node.args.args]
            self.assertIn("api_key", arg_names, msg=f"{node.name} is missing api_key")

            has_early_auth_check = any(
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Name)
                and stmt.value.func.id == "_check_api_key"
                for stmt in node.body[:3]
            )
            self.assertTrue(
                has_early_auth_check,
                msg=f"{node.name} is missing an early _check_api_key() call",
            )

        self.assertGreater(len(tool_functions), 0)

    def test_get_server_info_requires_key_when_auth_enabled(self):
        server = load_encode_server_module()
        server._REQUIRE_API_KEY = True
        server._API_KEY = "secret"

        with self.assertRaises(ValueError):
            server.get_server_info()

        info = server.get_server_info(api_key="secret")
        self.assertTrue(info["auth_required"])
        self.assertIn("load_mode", info)
        self.assertIn("incremental_batch_size", info)


class TestEncodeServerCacheReset(unittest.TestCase):
    """Verify cache-clearing tools clear the intended state."""

    def test_clear_cache_resets_singleton(self):
        server = load_encode_server_module()

        class StubEncode:
            def __init__(self):
                self.calls = []

            def clear_cache(self):
                self.calls.append("clear_cache")

            def clear_metadata_cache(self):
                self.calls.append("clear_metadata_cache")

        stub = StubEncode()
        server._REQUIRE_API_KEY = False
        server._encode_instance = stub

        result = server.clear_cache()

        self.assertEqual(result["message"], "Main experiments cache cleared")
        self.assertEqual(stub.calls, ["clear_cache"])
        self.assertIsNone(server._encode_instance)

    def test_clear_cache_with_metadata_clears_both_caches(self):
        server = load_encode_server_module()

        class StubEncode:
            def __init__(self):
                self.calls = []

            def clear_cache(self):
                self.calls.append("clear_cache")

            def clear_metadata_cache(self):
                self.calls.append("clear_metadata_cache")

        stub = StubEncode()
        server._REQUIRE_API_KEY = False
        server._encode_instance = stub

        result = server.clear_cache(clear_metadata=True)

        self.assertEqual(
            result["message"],
            "Main experiments cache and metadata cache cleared",
        )
        self.assertEqual(stub.calls, ["clear_cache", "clear_metadata_cache"])
        self.assertIsNone(server._encode_instance)


class TestEncodeServerConfiguration(unittest.TestCase):
    """Verify v0.4 server configuration is wired into ENCODE instance creation."""

    def test_get_encode_instance_uses_load_mode_settings(self):
        server = load_encode_server_module()
        captured_kwargs = {}

        class StubEncode:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        server._encode_instance = None
        server._SERVER_LOAD_MODE = "incremental"
        server._SERVER_INCREMENTAL_BATCH_SIZE = 123
        server._SERVER_BUILD_INDEX = True
        server._SERVER_ENABLE_METRICS = True

        with patch.object(server, "ENCODE", StubEncode):
            instance = server.get_encode_instance()

        self.assertIsInstance(instance, StubEncode)
        self.assertEqual(captured_kwargs["load_mode"], "incremental")
        self.assertEqual(captured_kwargs["incremental_batch_size"], 123)
        self.assertTrue(captured_kwargs["build_index"])
        self.assertTrue(captured_kwargs["enable_metrics"])

    def test_list_experiments_uses_summaries(self):
        server = load_encode_server_module()

        class StubEncode:
            def get_experiment_summaries(self):
                return [
                    {
                        "accession": "ENCSR000CDC",
                        "assay_title": "TF ChIP-seq",
                        "biosample_summary": "K562",
                        "organism": "Homo sapiens",
                        "status": "released",
                    }
                ]

            def get_organism_from_experiment(self, exp):
                return exp.get("organism")

        server._REQUIRE_API_KEY = False
        server._encode_instance = StubEncode()

        result = server.list_experiments(limit=10, offset=0)

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["experiments"][0]["accession"], "ENCSR000CDC")
        self.assertEqual(result["experiments"][0]["organism"], "Homo sapiens")


if __name__ == "__main__":
    unittest.main()