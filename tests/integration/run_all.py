#!/usr/bin/env python3
"""
DocsGPT Integration Test Runner

Runs all integration tests or specific modules.

Usage:
    python tests/integration/run_all.py                     # Run all tests
    python tests/integration/run_all.py --module chat       # Run specific module
    python tests/integration/run_all.py --module chat,agents # Run multiple modules
    python tests/integration/run_all.py --list              # List available modules
    python tests/integration/run_all.py --base-url URL      # Custom base URL
    python tests/integration/run_all.py --token TOKEN       # With auth token

Available modules:
    chat, sources, agents, conversations, prompts, tools, analytics,
    connectors, mcp, misc

Examples:
    # Run all tests
    python tests/integration/run_all.py

    # Run only chat and agent tests
    python tests/integration/run_all.py --module chat,agents

    # Run with custom server
    python tests/integration/run_all.py --base-url http://staging.example.com:7091
"""

import argparse
import os
import sys
from pathlib import Path

# Add parent directory to path for standalone execution
_THIS_DIR = Path(__file__).parent
_TESTS_DIR = _THIS_DIR.parent
_ROOT_DIR = _TESTS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tests.integration.base import Colors, generate_jwt_token
from tests.integration.test_chat import ChatTests
from tests.integration.test_sources import SourceTests
from tests.integration.test_agents import AgentTests
from tests.integration.test_conversations import ConversationTests
from tests.integration.test_prompts import PromptTests
from tests.integration.test_tools import ToolsTests
from tests.integration.test_analytics import AnalyticsTests
from tests.integration.test_connectors import ConnectorTests
from tests.integration.test_mcp import MCPTests
from tests.integration.test_misc import MiscTests


# Module registry
MODULES = {
    "chat": ChatTests,
    "sources": SourceTests,
    "agents": AgentTests,
    "conversations": ConversationTests,
    "prompts": PromptTests,
    "tools": ToolsTests,
    "analytics": AnalyticsTests,
    "connectors": ConnectorTests,
    "mcp": MCPTests,
    "misc": MiscTests,
}


def print_header(message: str) -> None:
    """Print a styled header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 70}{Colors.ENDC}\n")


def list_modules() -> None:
    """Print available test modules."""
    print_header("Available Test Modules")
    for name, cls in MODULES.items():
        test_count = len([m for m in dir(cls) if m.startswith("test_")])
        print(f"  {Colors.OKCYAN}{name:<15}{Colors.ENDC} - {test_count} tests")
    print()


def run_module(
    module_name: str,
    base_url: str,
    token: str | None,
    token_source: str,
) -> tuple[bool, int, int]:
    """
    Run a single test module.

    Returns:
        Tuple of (all_passed, passed_count, total_count)
    """
    cls = MODULES.get(module_name)
    if not cls:
        print(f"{Colors.FAIL}Unknown module: {module_name}{Colors.ENDC}")
        return False, 0, 0

    client = cls(base_url, token=token, token_source=token_source)
    success = client.run_all()

    passed = sum(1 for _, s, _ in client.test_results if s)
    total = len(client.test_results)

    return success, passed, total


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="DocsGPT Integration Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python tests/integration/run_all.py                     # Run all tests
    python tests/integration/run_all.py --module chat       # Run chat tests
    python tests/integration/run_all.py --module chat,agents  # Multiple modules
    python tests/integration/run_all.py --list              # List modules
        """,
    )

    parser.add_argument(
        "--base-url",
        default=os.getenv("DOCSGPT_BASE_URL", "http://localhost:7091"),
        help="Base URL of DocsGPT instance (default: http://localhost:7091)",
    )

    parser.add_argument(
        "--token",
        default=os.getenv("JWT_TOKEN"),
        help="JWT authentication token",
    )

    parser.add_argument(
        "--module", "-m",
        help="Specific module(s) to run, comma-separated (e.g., 'chat,agents')",
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available test modules",
    )

    args = parser.parse_args()

    # List modules and exit
    if args.list:
        list_modules()
        return 0

    # Determine token
    token = args.token
    token_source = "provided via --token" if token else "none"

    if not token:
        token, token_error = generate_jwt_token()
        if token:
            token_source = "auto-generated from local secret"
            print(f"{Colors.OKCYAN}[INFO] Using auto-generated JWT token{Colors.ENDC}")
        elif token_error:
            print(f"{Colors.WARNING}[WARN] Could not auto-generate token: {token_error}{Colors.ENDC}")
            print(f"{Colors.WARNING}[WARN] Tests requiring auth will be skipped{Colors.ENDC}")

    # Determine which modules to run
    if args.module:
        modules_to_run = [m.strip() for m in args.module.split(",")]
        # Validate modules
        invalid = [m for m in modules_to_run if m not in MODULES]
        if invalid:
            print(f"{Colors.FAIL}Unknown module(s): {', '.join(invalid)}{Colors.ENDC}")
            print(f"{Colors.OKCYAN}Available: {', '.join(MODULES.keys())}{Colors.ENDC}")
            return 1
    else:
        modules_to_run = list(MODULES.keys())

    # Print test plan
    print_header("DocsGPT Integration Test Suite")
    print(f"{Colors.OKCYAN}Base URL:{Colors.ENDC} {args.base_url}")
    print(f"{Colors.OKCYAN}Auth:{Colors.ENDC} {token_source}")
    print(f"{Colors.OKCYAN}Modules:{Colors.ENDC} {', '.join(modules_to_run)}")

    # Run tests
    results = {}
    total_passed = 0
    total_tests = 0

    for module_name in modules_to_run:
        success, passed, total = run_module(
            module_name,
            args.base_url,
            token,
            token_source,
        )
        results[module_name] = (success, passed, total)
        total_passed += passed
        total_tests += total

    # Print summary
    print_header("Overall Test Summary")

    print(f"\n{Colors.BOLD}Module Results:{Colors.ENDC}")
    for module_name, (success, passed, total) in results.items():
        status = f"{Colors.OKGREEN}PASS{Colors.ENDC}" if success else f"{Colors.FAIL}FAIL{Colors.ENDC}"
        print(f"  {status} - {module_name}: {passed}/{total} tests passed")

    print(f"\n{Colors.BOLD}Total:{Colors.ENDC} {total_passed}/{total_tests} tests passed")

    all_passed = all(success for success, _, _ in results.values())
    if all_passed:
        print(f"\n{Colors.OKGREEN}{Colors.BOLD}ALL TESTS PASSED{Colors.ENDC}")
        return 0
    else:
        failed_modules = [m for m, (s, _, _) in results.items() if not s]
        print(f"\n{Colors.FAIL}{Colors.BOLD}SOME TESTS FAILED{Colors.ENDC}")
        print(f"{Colors.FAIL}Failed modules: {', '.join(failed_modules)}{Colors.ENDC}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
