"""The ``application`` alias and the legacy Celery task names survive the rename to ``docsgpt``."""

import importlib
import sys
import warnings

import pytest


class TestApplicationAlias:
    def test_old_import_is_the_same_module_object(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            old = importlib.import_module("application.vectorstore.model_registry")
        new = importlib.import_module("docsgpt.vectorstore.model_registry")
        assert old is new
        assert sys.modules["application.vectorstore.model_registry"] is new

    def test_old_package_is_the_new_package(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import application  # noqa: F401
        assert sys.modules["application"] is importlib.import_module("docsgpt")

    def test_alias_warns_when_first_imported(self):
        """The shim warns once per process: on the import that executes it."""
        # Undo a previous import so the shim module body runs again.
        sys.meta_path[:] = [f for f in sys.meta_path if type(f).__name__ != "_AliasFinder"]
        for name in [m for m in sys.modules if m == "application" or m.startswith("application.")]:
            del sys.modules[name]
        with pytest.warns(FutureWarning, match="renamed to 'docsgpt'"):
            importlib.import_module("application")
        assert sys.modules["application"] is importlib.import_module("docsgpt")

    def test_missing_module_still_raises(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            with pytest.raises(ModuleNotFoundError):
                importlib.import_module("application.no_such_module")


class TestLegacyTaskNames:
    def test_every_task_answers_to_its_old_name(self):
        from docsgpt.celery_init import LEGACY_TASK_PREFIX, celery, register_legacy_task_names

        importlib.import_module("docsgpt.api.user.tasks")
        importlib.import_module("docsgpt.vectorstore.embeddings_tasks")
        added = register_legacy_task_names(celery)
        new_names = [n for n in celery.tasks if n.startswith("docsgpt.")]
        assert new_names, "no docsgpt.* tasks registered"
        for name in new_names:
            legacy = LEGACY_TASK_PREFIX + name[len("docsgpt."):]
            assert celery.tasks[legacy] is celery.tasks[name]
        assert register_legacy_task_names(celery) == 0, "second call must be idempotent"
        assert added <= len(new_names)

    def test_routes_and_reclaim_list_use_new_names(self):
        from docsgpt import celeryconfig
        from docsgpt.celery_init import _NO_RECLAIM_TASKS

        assert all(k.startswith("docsgpt.") for k in celeryconfig.task_routes)
        assert all(k.startswith("docsgpt.") for k in _NO_RECLAIM_TASKS)
        assert celeryconfig.redbeat_key_prefix == "redbeat:docsgpt:v2:"
