"""The ``application`` alias and the legacy Celery task names survive the rename to ``docsgpt``."""

import importlib
import runpy
import sys
import warnings

import pytest


def _quiet_import(name):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        return importlib.import_module(name)


class TestApplicationAlias:
    def test_old_import_is_the_same_module_object(self):
        old = _quiet_import("application.vectorstore.model_registry")
        new = importlib.import_module("docsgpt.vectorstore.model_registry")
        assert old is new
        assert sys.modules["application.vectorstore.model_registry"] is new

    def test_old_package_is_the_new_package(self):
        _quiet_import("application")
        assert sys.modules["application"] is importlib.import_module("docsgpt")

    def test_alias_keeps_the_real_spec(self):
        """Importing through the alias must not rename the shared module object."""
        module = _quiet_import("application.vectorstore.model_registry")
        assert module.__spec__.name == "docsgpt.vectorstore.model_registry"
        assert module.__name__ == "docsgpt.vectorstore.model_registry"

    def test_reload_works_on_the_shared_module(self):
        # docsgpt.version has no shared constants, so re-executing it in place is harmless.
        _quiet_import("application.version")
        module = importlib.import_module("docsgpt.version")
        reloaded = importlib.reload(module)
        assert reloaded is module
        assert reloaded.__spec__.name == "docsgpt.version"
        assert reloaded.get_version() == module.__version__

    def test_python_dash_m_through_the_alias(self):
        """``python -m application.x`` goes through runpy, which needs the loader's get_code.

        A real ``python -m`` starts a fresh interpreter, so the target module is
        not yet in ``sys.modules`` under the alias name when runpy looks it up;
        drop any entry an earlier test left so the lookup reaches the finder.
        """
        _quiet_import("application")
        sys.modules.pop("application.vectorstore.model_registry", None)
        globals_ = runpy.run_module("application.vectorstore.model_registry", run_name="__main__", alter_sys=True)
        assert "DEFAULT_NEW_INSTALL" in globals_

    def test_alias_warns_when_first_imported(self):
        """The shim warns once per process: on the import that executes it."""
        sys.meta_path[:] = [f for f in sys.meta_path if type(f).__name__ != "_AliasFinder"]
        for name in [m for m in sys.modules if m == "application" or m.startswith("application.")]:
            del sys.modules[name]
        with pytest.warns(FutureWarning, match="renamed to 'docsgpt'"):
            importlib.import_module("application")
        assert sys.modules["application"] is importlib.import_module("docsgpt")

    def test_missing_module_still_raises(self):
        _quiet_import("application")
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("application.no_such_module")


class TestLegacyTaskNames:
    def test_every_task_answers_to_its_old_name_as_its_own_object(self):
        from docsgpt.celery_init import LEGACY_TASK_PREFIX, celery, register_legacy_task_names

        importlib.import_module("docsgpt.api.user.tasks")
        importlib.import_module("docsgpt.vectorstore.embeddings_tasks")
        register_legacy_task_names(celery)
        new_names = [n for n in celery.tasks if n.startswith("docsgpt.")]
        assert new_names, "no docsgpt.* tasks registered"
        for name in new_names:
            legacy_name = LEGACY_TASK_PREFIX + name[len("docsgpt."):]
            canonical, legacy = celery.tasks[name], celery.tasks[legacy_name]
            assert legacy is not canonical, "an alias must be its own task object (its own tracer)"
            assert isinstance(legacy, type(canonical))
            assert legacy.name == legacy_name
            assert canonical.name == name
        assert register_legacy_task_names(celery) == 0, "second call must be idempotent"

    def test_routes_and_reclaim_list_use_new_names(self):
        from docsgpt import celeryconfig
        from docsgpt.celery_init import _NO_RECLAIM_TASKS

        assert all(k.startswith("docsgpt.") for k in celeryconfig.task_routes)
        assert all(k.startswith("docsgpt.") for k in _NO_RECLAIM_TASKS)
        assert celeryconfig.redbeat_key_prefix == "redbeat:docsgpt:", "the prefix must stay: redbeat updates named entries in place"
