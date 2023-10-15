import pytest
from openapi_parser import parse
from scripts.parser.file.openapi3_parser import OpenAPI3Parser


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
def test_get_base_urls(urls, expected_base_urls):
    assert OpenAPI3Parser().get_base_urls(urls) == expected_base_urls


def test_get_info_from_paths():
    file_path = "tests/test_openapi3.yaml"
    data = parse(file_path)
    path = data.paths[1]
    assert (
        OpenAPI3Parser().get_info_from_paths(path)
        == "\nget=Expected response to a valid request"
    )


def test_parse_file():
    file_path = "tests/test_openapi3.yaml"
    results_real = (
        "Base URL:http://petstore.swagger.io,https://api.example.com\nPath1: "
        + "/pets\ndescription: None\nparameters: []\nmethods: \n"
        + "get=A paged array of pets\npost=Null "
        + "response\nPath2: /pets/{petId}\ndescription: None\n"
        + "parameters: []\nmethods: "
        + "\nget=Expected response to a valid request\n"
    )
    openapi_parser_test = OpenAPI3Parser()
    results = openapi_parser_test.parse_file(file_path)
    assert results == results_real


if __name__ == "__main__":
    pytest.main()
