from unittest.mock import Mock

import pytest
import uuid
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestGetUserId:

    def test_returns_user_id_from_decoded_token(self, app):
        from application.api.user.utils import get_user_id

        with app.test_request_context():
            from flask import request

            request.decoded_token = {"sub": "user_123"}
            assert get_user_id() == "user_123"

    def test_returns_none_when_no_decoded_token(self, app):
        from application.api.user.utils import get_user_id

        with app.test_request_context():
            assert get_user_id() is None

    def test_returns_none_when_decoded_token_has_no_sub(self, app):
        from application.api.user.utils import get_user_id

        with app.test_request_context():
            from flask import request

            request.decoded_token = {}
            assert get_user_id() is None


@pytest.mark.unit
class TestRequireAuth:

    def test_allows_authenticated_request(self, app):
        from application.api.user.utils import require_auth

        @require_auth
        def protected():
            return "ok"

        with app.test_request_context():
            from flask import request

            request.decoded_token = {"sub": "user_123"}
            assert protected() == "ok"

    def test_returns_401_when_unauthenticated(self, app):
        from application.api.user.utils import require_auth

        @require_auth
        def protected():
            return "ok"

        with app.test_request_context():
            result = protected()
            assert result.status_code == 401


@pytest.mark.unit
class TestSuccessResponse:

    def test_default_success_response(self, app):
        from application.api.user.utils import success_response

        with app.app_context():
            resp = success_response()
            assert resp.status_code == 200
            assert resp.json["success"] is True

    def test_success_response_with_data(self, app):
        from application.api.user.utils import success_response

        with app.app_context():
            resp = success_response({"items": [1, 2], "total": 2})
            assert resp.status_code == 200
            assert resp.json["success"] is True
            assert resp.json["items"] == [1, 2]
            assert resp.json["total"] == 2

    def test_success_response_custom_status(self, app):
        from application.api.user.utils import success_response

        with app.app_context():
            resp = success_response({"id": "new"}, 201)
            assert resp.status_code == 201


@pytest.mark.unit
class TestErrorResponse:

    def test_default_error_response(self, app):
        from application.api.user.utils import error_response

        with app.app_context():
            resp = error_response("Something went wrong")
            assert resp.status_code == 400
            assert resp.json["success"] is False
            assert resp.json["message"] == "Something went wrong"

    def test_error_response_custom_status(self, app):
        from application.api.user.utils import error_response

        with app.app_context():
            resp = error_response("Not found", 404)
            assert resp.status_code == 404

    def test_error_response_extra_kwargs(self, app):
        from application.api.user.utils import error_response

        with app.app_context():
            resp = error_response("Bad", 400, errors=["field1", "field2"])
            assert resp.json["errors"] == ["field1", "field2"]


@pytest.mark.unit
class TestValidateObjectId:

    def test_valid_object_id(self, app):
        from application.api.user.utils import validate_object_id

        with app.app_context():
            oid = uuid.uuid4().hex[:24]
            result, error = validate_object_id(oid)
            assert str(result) == oid
            assert error is None

    def test_invalid_object_id(self, app):
        from application.api.user.utils import validate_object_id

        with app.app_context():
            result, error = validate_object_id("not-a-valid-id")
            assert result is None
            assert error.status_code == 400
            assert "Invalid" in error.json["message"]

    def test_custom_resource_name(self, app):
        from application.api.user.utils import validate_object_id

        with app.app_context():
            _, error = validate_object_id("bad", "Workflow")
            assert "Workflow" in error.json["message"]


@pytest.mark.unit
class TestValidatePagination:

    def test_default_pagination(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/?limit=10&skip=0"):
            limit, skip, error = validate_pagination()
            assert limit == 10
            assert skip == 0
            assert error is None

    def test_uses_defaults_when_no_params(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/"):
            limit, skip, error = validate_pagination()
            assert limit == 20
            assert skip == 0
            assert error is None

    def test_enforces_max_limit(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/?limit=500"):
            limit, _, _ = validate_pagination(max_limit=100)
            assert limit == 100

    def test_invalid_limit(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/?limit=-1"):
            _, _, error = validate_pagination()
            assert error is not None
            assert error.status_code == 400

    def test_invalid_skip(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/?skip=-1"):
            _, _, error = validate_pagination()
            assert error is not None

    def test_non_numeric_values(self, app):
        from application.api.user.utils import validate_pagination

        with app.test_request_context("/?limit=abc"):
            _, _, error = validate_pagination()
            assert error is not None


@pytest.mark.unit
class TestCheckResourceOwnership:

    def test_returns_resource_when_owned(self, app):
        from application.api.user.utils import check_resource_ownership

        with app.app_context():
            collection = Mock()
            oid = uuid.uuid4().hex[:24]
            doc = {"_id": oid, "user": "user1", "name": "test"}
            collection.find_one.return_value = doc

            resource, error = check_resource_ownership(collection, oid, "user1")
            assert resource == doc
            assert error is None

    def test_returns_404_when_not_found(self, app):
        from application.api.user.utils import check_resource_ownership

        with app.app_context():
            collection = Mock()
            collection.find_one.return_value = None

            resource, error = check_resource_ownership(
                collection, uuid.uuid4().hex[:24], "user1", "Workflow"
            )
            assert resource is None
            assert error.status_code == 404
            assert "Workflow" in error.json["message"]


@pytest.mark.unit
class TestSerializeObjectId:

    def test_converts_id_to_string(self):
        from application.api.user.utils import serialize_object_id

        oid = uuid.uuid4().hex[:24]
        obj = {"_id": oid, "name": "test"}
        result = serialize_object_id(obj)
        assert result["id"] == str(oid)
        assert "_id" not in result

    def test_custom_field_names(self):
        from application.api.user.utils import serialize_object_id

        oid = uuid.uuid4().hex[:24]
        obj = {"custom_id": oid}
        result = serialize_object_id(obj, id_field="custom_id", new_field="uid")
        assert result["uid"] == str(oid)
        assert "custom_id" not in result

    def test_no_id_field_present(self):
        from application.api.user.utils import serialize_object_id

        obj = {"name": "test"}
        result = serialize_object_id(obj)
        assert "id" not in result


@pytest.mark.unit
class TestSerializeList:

    def test_applies_serializer_to_all_items(self):
        from application.api.user.utils import serialize_list

        items = [{"_id": uuid.uuid4().hex[:24]}, {"_id": uuid.uuid4().hex[:24]}]

        def serializer(item):
            return {"id": str(item["_id"])}

        result = serialize_list(items, serializer)
        assert len(result) == 2
        assert all("id" in r for r in result)

    def test_empty_list(self):
        from application.api.user.utils import serialize_list

        assert serialize_list([], lambda x: x) == []


@pytest.mark.unit
class TestRequireFields:

    def test_allows_valid_request(self, app):
        from application.api.user.utils import require_fields

        @require_fields(["name", "email"])
        def handler():
            return "ok"

        with app.test_request_context(
            "/", method="POST", json={"name": "Alice", "email": "a@b.com"}
        ):
            assert handler() == "ok"

    def test_rejects_missing_fields(self, app):
        from application.api.user.utils import require_fields

        @require_fields(["name", "email"])
        def handler():
            return "ok"

        with app.test_request_context("/", method="POST", json={"name": "Alice"}):
            result = handler()
            assert result.status_code == 400
            assert "email" in result.json["message"]

    def test_rejects_empty_body(self, app):
        from application.api.user.utils import require_fields

        @require_fields(["name"])
        def handler():
            return "ok"

        with app.test_request_context(
            "/", method="POST", json={}
        ):
            result = handler()
            assert result.status_code == 400


@pytest.mark.unit
class TestSafeDbOperation:

    def test_returns_result_on_success(self, app):
        from application.api.user.utils import safe_db_operation

        with app.app_context():
            result, error = safe_db_operation(lambda: {"inserted": True})
            assert result == {"inserted": True}
            assert error is None

    def test_returns_error_on_exception(self, app):
        from application.api.user.utils import safe_db_operation

        with app.app_context():
            result, error = safe_db_operation(
                lambda: (_ for _ in ()).throw(RuntimeError("db error")),
                "Operation failed",
            )
            assert result is None
            assert error.status_code == 400
            assert error.json["message"] == "Operation failed"

    def test_hides_exception_details(self, app):
        from application.api.user.utils import safe_db_operation

        with app.app_context():
            _, error = safe_db_operation(
                lambda: (_ for _ in ()).throw(RuntimeError("secret credentials")),
                "Failed",
            )
            assert "credentials" not in error.json["message"]


@pytest.mark.unit
class TestValidateEnum:

    def test_valid_value(self, app):
        from application.api.user.utils import validate_enum

        with app.app_context():
            assert validate_enum("draft", ["draft", "published"], "status") is None

    def test_invalid_value(self, app):
        from application.api.user.utils import validate_enum

        with app.app_context():
            error = validate_enum("unknown", ["draft", "published"], "status")
            assert error.status_code == 400
            assert "status" in error.json["message"]


@pytest.mark.unit
class TestExtractSortParams:

    def test_defaults(self, app):
        from application.api.user.utils import extract_sort_params

        with app.test_request_context("/"):
            field, order = extract_sort_params()
            assert field == "created_at"
            assert order == -1

    def test_custom_params(self, app):
        from application.api.user.utils import extract_sort_params

        with app.test_request_context("/?sort=name&order=asc"):
            field, order = extract_sort_params()
            assert field == "name"
            assert order == 1

    def test_enforces_allowed_fields(self, app):
        from application.api.user.utils import extract_sort_params

        with app.test_request_context("/?sort=forbidden_field"):
            field, _ = extract_sort_params(allowed_fields=["name", "date"])
            assert field == "created_at"

    def test_desc_order(self, app):
        from application.api.user.utils import extract_sort_params

        with app.test_request_context("/?order=desc"):
            _, order = extract_sort_params()
            assert order == -1
