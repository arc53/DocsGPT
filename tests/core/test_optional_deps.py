"""Optional-extra bookkeeping: hints name the extra, require() explains absence."""

import sys
import types
from unittest.mock import patch

import pytest

from docsgpt.core import optional_deps


class TestExtras:
    def test_every_extra_module_maps_back(self):
        for extra, modules in optional_deps.EXTRAS.items():
            for module in modules:
                assert optional_deps.extra_for(module) == extra

    def test_submodule_resolves_to_its_extra(self):
        assert optional_deps.extra_for("docling.document_converter") == "docling"

    def test_unknown_module_has_no_extra(self):
        assert optional_deps.extra_for("flask") is None

    def test_install_hint_names_every_install_route(self):
        hint = optional_deps.install_hint("milvus")
        assert "pip install -r docsgpt/requirements-milvus.txt" in hint
        assert "--extra milvus" in hint
        assert "EXTRAS=milvus" in hint


class TestMissingMessage:
    def test_extra_module_points_at_the_extra(self):
        message = optional_deps.missing_message("pymilvus", "VECTOR_STORE=milvus")
        assert "pymilvus is not installed (VECTOR_STORE=milvus)" in message
        assert "'milvus' extra" in message
        assert optional_deps.install_hint("milvus") in message

    def test_plain_module_gets_a_pip_line(self):
        assert optional_deps.missing_message("boto3") == "boto3 is not installed. Install it with: pip install boto3"


class TestRequire:
    def test_returns_the_module_when_present(self):
        assert optional_deps.require("json").dumps({}) == "{}"

    def test_absent_module_raises_with_hint(self):
        with patch.dict(sys.modules, {"pymilvus": None}):
            with pytest.raises(ImportError) as excinfo:
                optional_deps.require("pymilvus", "VECTOR_STORE=milvus")
        assert "'milvus' extra" in str(excinfo.value)


class TestIsAvailable:
    def test_stubbed_module_counts_as_present(self):
        with patch.dict(sys.modules, {"docling": types.ModuleType("docling")}):
            assert optional_deps.is_available("docling.document_converter")

    def test_blocked_module_counts_as_absent(self):
        with patch.dict(sys.modules, {"docling": None}):
            assert not optional_deps.is_available("docling")
