import argparse
import json
import sys
import urllib.error
import urllib.request

from application.core.service_checks import required_service_checks, summarize_checks


def _check_backend_endpoint(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            return response.status == 200
    except urllib.error.URLError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="DocsGPT healthcheck helper")
    parser.add_argument(
        "--target",
        choices=["dependencies", "worker", "backend"],
        default="dependencies",
        help="Check dependency services or backend HTTP endpoint",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:7091/api/health",
        help="Backend URL used when target=backend",
    )
    args = parser.parse_args()

    if args.target == "backend":
        is_healthy = _check_backend_endpoint(args.url)
        print(json.dumps({"target": "backend", "healthy": is_healthy}, ensure_ascii=True))
        return 0 if is_healthy else 1

    checks = required_service_checks()
    all_ok, payload = summarize_checks(checks)
    print(
        json.dumps(
            {"target": args.target, "healthy": all_ok, "checks": payload},
            ensure_ascii=True,
        )
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
