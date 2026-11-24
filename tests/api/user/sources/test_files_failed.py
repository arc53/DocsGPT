"""``_files_failed``: how many files a connector source's last sync couldn't read, for the listing."""

import pytest

from docsgpt.api.user.sources.routes import _files_failed


@pytest.mark.unit
@pytest.mark.parametrize("remote_data, expected", [
    ({"files_failed": 1200, "failed_files": [{"id": "a"}]}, 1200),
    ({"failed_files": [{"id": "a"}, {"id": "b"}]}, 2),
    ('{"failed_files": [{"id": "a"}]}', 1),
    ("not json", 0),
    (["not", "a", "dict"], 0),
    ({"files_failed": True}, 0),
    (None, 0),
], ids=["full-count", "list", "json-text", "bad-json", "not-a-dict", "bool", "none"])
def test_files_failed(remote_data, expected):
    assert _files_failed({"remote_data": remote_data}) == expected
