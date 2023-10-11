from urllib.parse import urlparse

from openapi_parser import parse

from base_parser import BaseParser


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

    def get_info_from_paths(self, path):
        info = ""
        for operation in path.operations:
            info += (
                f"\n{operation.method.value}="
                f"{operation.responses[0].description}"
            )
        return info

    def parse_file(self, file_path):
        data = parse(file_path)
        results = ""
        base_urls = self.get_base_urls(link.url for link in data.servers)
        base_urls = ",".join([base_url for base_url in base_urls])
        results += f"Base URL:{base_urls}\n"
        i = 1
        for path in data.paths:
            info = self.get_info_from_paths(path)
            results += (
                f"Path{i}: {path.url}\n"
                f"description: {path.description}\n"
                f"parameters: {path.parameters}\nmethods: {info}\n"
            )
            i += 1
        with open("results.txt", "w") as f:
            f.write(results)
