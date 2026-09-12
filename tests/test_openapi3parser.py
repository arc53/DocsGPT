import pytest
from docsgpt.parser.file.openapi3_parser import OpenAPI3Parser
from openapi_parser import parse


@pytest.mark.parametrize(
    "urls, expected_base_urls",
    [
        (
            [
                "http://petstore.swagger.io/v1",
                "https://api.example.com/v1/resource",
                "https://api.example.com/v1/another/resource",
                "https://api.example.com/v1/some/endpoint",
            ],
            ["http://petstore.swagger.io", "https://api.example.com"],
        ),
    ],
)
@pytest.mark.unit
def test_get_base_urls(urls, expected_base_urls):
    assert OpenAPI3Parser().get_base_urls(urls) == expected_base_urls


@pytest.mark.unit
def test_get_info_from_paths():
    file_path = "tests/test_openapi3.yaml"
    data = parse(file_path)
    path_item = data.paths["/pets/{petId}"]
    assert (
        OpenAPI3Parser().get_info_from_paths(path_item)
        == "\nget=Expected response to a valid request"
    )


@pytest.mark.unit
def test_get_operations_follows_spec_method_order():
    """openapi-parser 2.x exposes one field per method instead of an
    ``operations`` list; the rendered order stays the spec's."""
    data = parse("tests/test_openapi3.yaml")
    path_item = data.paths["/pets"]
    assert [method for method, _ in OpenAPI3Parser().get_operations(path_item)] == [
        "get",
        "post",
    ]


@pytest.mark.unit
def test_parse_file():
    file_path = "tests/test_openapi3.yaml"
    results_expected = (
        "Base URL:http://petstore.swagger.io,https://api.example.com\nPath1: "
        + "/pets\ndescription: None\nparameters: []\nmethods: \n"
        + "get=A paged array of pets\npost=Null "
        + "response\nPath2: /pets/{petId}\ndescription: None\n"
        + "parameters: []\nmethods: "
        + "\nget=Expected response to a valid request\n"
    )
    openapi_parser_test = OpenAPI3Parser()
    results = openapi_parser_test.parse_file(file_path)
    assert results == results_expected


if __name__ == "__main__":
    pytest.main()
