from unittest.mock import patch

import pytest

from application.logging import build_stack_data


@pytest.mark.unit
class TestBuildStackData:

    def test_raises_on_none_obj(self):
        with pytest.raises(ValueError, match="cannot be None"):
            build_stack_data(None)

    def test_auto_discovers_attributes(self):
        class Obj:
            name = "test"
            count = 5

        result = build_stack_data(Obj())
        assert result["name"] == "test"
        assert result["count"] == 5

    def test_include_attributes(self):
        class Obj:
            name = "test"
            count = 5
            hidden = "secret"

        result = build_stack_data(Obj(), include_attributes=["name"])
        assert result["name"] == "test"
        assert "hidden" not in result

    def test_exclude_attributes(self):
        class Obj:
            pass

        obj = Obj()
        obj.name = "test"
        obj.secret = "hidden"
        result = build_stack_data(
            obj,
            include_attributes=["name", "secret"],
            exclude_attributes=["secret"],
        )
        assert "secret" not in result
        assert result["name"] == "test"

    def test_list_of_dicts(self):
        class Obj:
            pass

        obj = Obj()
        obj.items = [{"a": 1}, {"b": 2}]
        result = build_stack_data(obj, include_attributes=["items"])
        assert result["items"] == [{"a": 1}, {"b": 2}]

    def test_list_of_objects(self):
        class Inner:
            def __init__(self, v):
                self.val = v

        class Obj:
            pass

        obj = Obj()
        obj.items = [Inner(1), Inner(2)]
        result = build_stack_data(obj, include_attributes=["items"])
        assert result["items"] == [{"val": 1}, {"val": 2}]

    def test_list_of_strings(self):
        class Obj:
            pass

        obj = Obj()
        obj.tags = [1, 2, 3]
        result = build_stack_data(obj, include_attributes=["tags"])
        assert result["tags"] == ["1", "2", "3"]

    def test_dict_attribute(self):
        class Obj:
            pass

        obj = Obj()
        obj.meta = {"key": 123}
        result = build_stack_data(obj, include_attributes=["meta"])
        assert result["meta"] == {"key": "123"}

    def test_none_attribute_skipped(self):
        class Obj:
            pass

        obj = Obj()
        obj.empty = None
        result = build_stack_data(obj, include_attributes=["empty"])
        assert "empty" not in result

    def test_custom_data_merged(self):
        class Obj:
            name = "test"

        result = build_stack_data(
            Obj(),
            include_attributes=["name"],
            custom_data={"extra": "val"},
        )
        assert result["extra"] == "val"

    def test_attribute_error_handled(self):
        class Obj:
            pass

        result = build_stack_data(Obj(), include_attributes=["nonexistent"])
        assert result == {}


@pytest.mark.unit
class TestLogActivity:

    def test_log_activity_decorator_yields(self):
        from application.logging import log_activity

        class FakeAgent:
            endpoint = "test"
            user = "user1"
            user_api_key = "key1"
            query = "hi"

        @log_activity()
        def my_gen(agent, log_context=None):
            yield "chunk1"
            yield "chunk2"

        with patch("application.logging._log_to_mongodb"):
            result = list(my_gen(FakeAgent()))
        assert result == ["chunk1", "chunk2"]

    def test_log_activity_handles_exception(self):
        from application.logging import log_activity

        class FakeAgent:
            endpoint = "test"
            user = "user1"
            user_api_key = ""

        @log_activity()
        def failing_gen(agent, log_context=None):
            yield "ok"
            raise RuntimeError("boom")

        with patch("application.logging._log_to_mongodb"), pytest.raises(
            RuntimeError, match="boom"
        ):
            list(failing_gen(FakeAgent()))


