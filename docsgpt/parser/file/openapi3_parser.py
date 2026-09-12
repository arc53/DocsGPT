from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

from openapi_parser import parse

try:
    from docsgpt.parser.file.base_parser import BaseParser
except ModuleNotFoundError:
    from base_parser import BaseParser

# openapi-parser 2.x models a path item as one field per HTTP method rather
# than an ``operations`` list, so the methods are read in the order the
# OpenAPI spec declares them.
_HTTP_METHODS: Tuple[str, ...] = (
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
)


class OpenAPI3Parser(BaseParser):
    def init_parser(self) -> None:
        return super().init_parser()

    def get_base_urls(self, urls):
        base_urls = []
        for i in urls:
            parsed_url = urlparse(i)
            base_url = parsed_url.scheme + "://" + parsed_url.netloc
            if base_url not in base_urls:
                base_urls.append(base_url)
        return base_urls

    def get_operations(self, path_item) -> Iterable[Tuple[str, object]]:
        """Yield ``(method, operation)`` for every method the path item defines."""
        for method in _HTTP_METHODS:
            operation = getattr(path_item, method, None)
            if operation is not None:
                yield method, operation

    def get_info_from_paths(self, path_item) -> str:
        """Render one line per method as ``\\n<method>=<first response description>``."""
        info = ""
        for method, operation in self.get_operations(path_item):
            responses = operation.responses or {}
            first = next(iter(responses.values()), None)
            description = getattr(first, "description", None)
            info += f"\n{method}={description}"
        return info

    def parse_file(self, file_path):
        data = parse(file_path)
        results = ""
        base_urls = self.get_base_urls(link.url for link in data.servers)
        base_urls = ",".join([base_url for base_url in base_urls])
        results += f"Base URL:{base_urls}\n"
        paths: Optional[Dict] = data.paths or {}
        for i, (url, path_item) in enumerate(paths.items(), start=1):
            info = self.get_info_from_paths(path_item)
            results += (
                f"Path{i}: {url}\n"
                f"description: {path_item.description}\n"
                f"parameters: {path_item.parameters or []}\nmethods: {info}\n"
            )
        with open("results.txt", "w") as f:
            f.write(results)
        return results
