import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from application.api.answer.services.compression import CompressionService
from application.api.answer.services.compression.threshold_checker import (
    CompressionThresholdChecker,
)
from application.api.answer.services.compression.token_counter import TokenCounter
from application.api.answer.services.compression.prompt_builder import (
    CompressionPromptBuilder,
)
from application.core.settings import settings


@pytest.fixture
def mock_llm():
    """Create a mock LLM for testing"""
    llm = Mock()
    llm.gen = Mock()
    return llm


@pytest.fixture
def compression_service(mock_llm):
    """Create a CompressionService instance with mock LLM"""
    return CompressionService(llm=mock_llm, model_id="gpt-4o")


@pytest.fixture
def threshold_checker():
    """Create a ThresholdChecker instance"""
    return CompressionThresholdChecker()


@pytest.fixture
def prompt_builder():
    """Create a PromptBuilder instance"""
    return CompressionPromptBuilder()


@pytest.fixture
def sample_conversation():
    """Create a sample conversation for testing"""
    return {
        "_id": "test_conversation_id",
        "user": "test_user",
        "date": datetime.now(timezone.utc),
        "name": "Test Conversation",
        "queries": [
            {
                "prompt": "What is Python?",
                "response": "Python is a high-level programming language.",
                "thought": "",
                "sources": [],
                "tool_calls": [],
                "timestamp": datetime.now(timezone.utc),
            },
            {
                "prompt": "How do I install it?",
                "response": "You can install Python from python.org",
                "thought": "",
                "sources": [],
                "tool_calls": [],
                "timestamp": datetime.now(timezone.utc),
            },
            {
                "prompt": "What are some popular libraries?",
                "response": "Popular Python libraries include NumPy, Pandas, Django, Flask, etc.",
                "thought": "",
                "sources": [],
                "tool_calls": [],
                "timestamp": datetime.now(timezone.utc),
            },
        ],
    }


@pytest.fixture
def large_conversation():
    """Create a large conversation that exceeds threshold"""
    queries = []
    for i in range(100):
        queries.append(
            {
                "prompt": f"Question {i}: " + ("test " * 100),  # ~400 tokens each
                "response": f"Answer {i}: " + ("response " * 100),  # ~400 tokens each
                "thought": "",
                "sources": [],
                "tool_calls": [],
                "timestamp": datetime.now(timezone.utc),
            }
        )

    return {
        "_id": "large_conversation_id",
        "user": "test_user",
        "date": datetime.now(timezone.utc),
        "name": "Large Conversation",
        "queries": queries,
    }


class TestCompressionService:
    """Test suite for CompressionService"""

    def test_initialization(self, mock_llm):
        """Test CompressionService initialization"""
        service = CompressionService(llm=mock_llm, model_id="gpt-4o")

        assert service.llm == mock_llm
        assert service.model_id == "gpt-4o"
        assert service.prompt_builder is not None
        assert service.prompt_builder.version == settings.COMPRESSION_PROMPT_VERSION

    @patch("application.api.answer.services.compression.threshold_checker.get_token_limit")
    def test_should_compress_below_threshold(
        self, mock_get_token_limit, threshold_checker, sample_conversation
    ):
        """Test that compression is not triggered when below threshold"""
        mock_get_token_limit.return_value = 128000  # GPT-4o limit

        # Small conversation should not trigger compression
        result = threshold_checker.should_compress(
            sample_conversation, model_id="gpt-4o"
        )

        assert result is False

    @patch("application.api.answer.services.compression.threshold_checker.get_token_limit")
    def test_should_compress_above_threshold(
        self, mock_get_token_limit, threshold_checker, large_conversation
    ):
        """Test that compression is triggered when above threshold"""
        mock_get_token_limit.return_value = 10000  # Lower limit to ensure large conversation exceeds threshold

        # Large conversation should trigger compression (100 queries with repeated text)
        # Threshold at 80% of 10k = 8k tokens, so large_conversation > 8k should trigger
        result = threshold_checker.should_compress(
            large_conversation, model_id="gpt-4o"
        )

        assert result is True

    @patch("application.api.answer.services.compression.threshold_checker.get_token_limit")
    def test_should_compress_at_exact_threshold(
        self, mock_get_token_limit, threshold_checker
    ):
        """Test compression trigger at exact 80% threshold"""
        mock_get_token_limit.return_value = 1000

        # Create conversation with exactly 800 tokens (80% of 1000)
        conversation = {
            "queries": [
                {
                    "prompt": "a " * 200,  # ~200 tokens
                    "response": "b " * 200,  # ~200 tokens
                },
                {
                    "prompt": "c " * 200,  # ~200 tokens
                    "response": "d " * 200,  # ~200 tokens
                },
            ]
        }

        result = threshold_checker.should_compress(conversation, model_id="test-model")

        # Should trigger at or above 80%
        assert result is True

    def test_compress_conversation_basic(self, compression_service, sample_conversation):
        """Test basic conversation compression"""
        # Mock LLM response
        mock_summary = """
        <analysis>
        The conversation covers Python basics and installation.
        </analysis>

        <summary>
        1. Primary Request and Intent:
           User asked about Python and how to install it.

        2. Key Concepts:
           - Python programming language
           - Installation process

        3. Files and Code Sections:
           None

        4. Errors and fixes:
           None

        5. Problem Solving:
           Explained Python installation from python.org

        6. All user messages:
           - What is Python?
           - How do I install it?
           - What are some popular libraries?

        7. Pending Tasks:
           None

        8. Current Work:
           Provided information about popular Python libraries.

        9. Optional Next Step:
           None
        </summary>
        """
        compression_service.llm.gen.return_value = mock_summary

        # Compress first 2 queries
        result = compression_service.compress_conversation(
            conversation=sample_conversation, compress_up_to_index=1
        )

        # Verify LLM was called
        assert compression_service.llm.gen.called

        # Verify result is a CompressionMetadata object
        assert hasattr(result, 'timestamp')
        assert result.query_index == 1
        assert hasattr(result, 'compressed_summary')
        assert result.original_token_count > 0
        assert result.compressed_token_count > 0
        assert result.compression_ratio > 0
        assert result.model_used == "gpt-4o"
        assert result.compression_prompt_version == settings.COMPRESSION_PROMPT_VERSION

        # Verify summary was extracted correctly (without analysis tags)
        assert "<analysis>" not in result.compressed_summary
        assert "Primary Request and Intent" in result.compressed_summary

    def test_compress_conversation_with_tool_calls(self, compression_service):
        """Test compression of conversation with tool calls"""
        conversation = {
            "queries": [
                {
                    "prompt": "Search for Python tutorials",
                    "response": "I'll search for Python tutorials.",
                    "thought": "Need to use search tool",
                    "sources": [],
                    "tool_calls": [
                        {
                            "tool_name": "search_tool",
                            "action_name": "search",
                            "arguments": {"query": "Python tutorials"},
                            "result": "Found 100 tutorials",
                            "status": "completed",
                        }
                    ],
                    "timestamp": datetime.now(timezone.utc),
                }
            ]
        }

        mock_summary = "<summary>Test summary with tools</summary>"
        compression_service.llm.gen.return_value = mock_summary

        compression_service.compress_conversation(
            conversation=conversation, compress_up_to_index=0
        )

        # Verify tool calls are included in compression prompt
        call_args = compression_service.llm.gen.call_args
        messages = call_args[1]["messages"]
        user_message = messages[1]["content"]

        assert "Tool Calls:" in user_message
        assert "search_tool" in user_message

    def test_compress_conversation_invalid_index(
        self, compression_service, sample_conversation
    ):
        """Test compression with invalid index raises error"""
        with pytest.raises(ValueError, match="Invalid compress_up_to_index"):
            compression_service.compress_conversation(
                conversation=sample_conversation,
                compress_up_to_index=100,  # Invalid - conversation only has 3 queries
            )

    def test_get_compressed_context_no_compression(
        self, compression_service, sample_conversation
    ):
        """Test getting context when no compression exists"""
        summary, recent = compression_service.get_compressed_context(
            sample_conversation
        )

        assert summary is None
        assert len(recent) == 3  # All queries returned

    def test_get_compressed_context_with_compression(self, compression_service):
        """Test getting context when compression exists"""
        conversation = {
            "queries": [
                {"prompt": "Q1", "response": "A1"},
                {"prompt": "Q2", "response": "A2"},
                {"prompt": "Q3", "response": "A3"},
                {"prompt": "Q4", "response": "A4"},
                {"prompt": "Q5", "response": "A5"},
            ],
            "compression_metadata": {
                "is_compressed": True,
                "last_compression_at": datetime.now(timezone.utc),
                "compression_points": [
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 2,  # Compressed up to Q3
                        "compressed_summary": "Summary of Q1-Q3",
                        "original_token_count": 100,
                        "compressed_token_count": 20,
                        "compression_ratio": 5.0,
                    }
                ],
            },
        }

        summary, recent = compression_service.get_compressed_context(
            conversation
        )

        assert summary == "Summary of Q1-Q3"
        assert len(recent) == 2  # Q4 and Q5 (after compression point)
        assert recent[0]["prompt"] == "Q4"
        assert recent[1]["prompt"] == "Q5"

    def test_get_compressed_context_multiple_compressions(self, compression_service):
        """Test getting context when multiple compressions exist"""
        conversation = {
            "queries": [
                {"prompt": f"Q{i}", "response": f"A{i}"} for i in range(1, 11)
            ],
            "compression_metadata": {
                "is_compressed": True,
                "last_compression_at": datetime.now(timezone.utc),
                "compression_points": [
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 4,  # First compression
                        "compressed_summary": "First compression summary",
                        "original_token_count": 100,
                        "compressed_token_count": 20,
                    },
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 7,  # Second compression
                        "compressed_summary": "Second compression summary (includes first)",
                        "original_token_count": 150,
                        "compressed_token_count": 30,
                    },
                ],
            },
        }

        summary, recent = compression_service.get_compressed_context(
            conversation
        )

        # Should use the most recent compression
        assert summary == "Second compression summary (includes first)"
        assert len(recent) == 2  # Q9 and Q10 (after compression point at index 7)
        assert recent[0]["prompt"] == "Q9"
        assert recent[1]["prompt"] == "Q10"

    def test_extract_summary_with_tags(self, compression_service):
        """Test summary extraction with analysis and summary tags"""
        llm_response = """
        <analysis>
        This is my analysis of the conversation.
        It has multiple lines.
        </analysis>

        <summary>
        This is the actual summary.
        It should be extracted.
        </summary>
        """

        result = compression_service._extract_summary(llm_response)

        assert "<analysis>" not in result
        assert "This is the actual summary" in result
        assert "my analysis" not in result

    def test_extract_summary_without_tags(self, compression_service):
        """Test summary extraction when no tags present"""
        llm_response = "This is a plain summary without tags."

        result = compression_service._extract_summary(llm_response)

        assert result == "This is a plain summary without tags."

    def test_count_tokens_in_queries(self, sample_conversation):
        """Test token counting in queries"""
        queries = sample_conversation["queries"]

        token_count = TokenCounter.count_query_tokens(queries)

        # Should count all prompts and responses
        assert token_count > 0

    def test_count_tokens_with_tool_calls(self):
        """Test token counting includes tool calls"""
        queries = [
            {
                "prompt": "Test prompt",
                "response": "Test response",
                "tool_calls": [
                    {
                        "tool_name": "test_tool",
                        "action_name": "test_action",
                        "arguments": {"arg": "value"},
                        "result": "Tool result",
                    }
                ],
            }
        ]

        token_count_with_tools = TokenCounter.count_query_tokens(
            queries, include_tool_calls=True
        )
        token_count_without_tools = TokenCounter.count_query_tokens(
            queries, include_tool_calls=False
        )

        assert token_count_with_tools > token_count_without_tools

    def test_format_conversation_for_compression(
        self, prompt_builder, sample_conversation
    ):
        """Test conversation formatting for compression prompt"""
        queries = sample_conversation["queries"]

        formatted = prompt_builder._format_conversation(queries)

        # Verify formatting includes all messages
        assert "Message 1" in formatted
        assert "What is Python?" in formatted
        assert "Python is a high-level programming language" in formatted
        assert "Message 2" in formatted
        assert "How do I install it?" in formatted

    def test_build_compression_prompt_basic(self, prompt_builder):
        """Test compression prompt building"""
        queries = [
            {"prompt": "Q1", "response": "A1", "tool_calls": [], "sources": []},
            {"prompt": "Q2", "response": "A2", "tool_calls": [], "sources": []},
        ]

        messages = prompt_builder.build_prompt(queries)

        assert len(messages) == 2  # System and user messages
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "conversation to summarize" in messages[1]["content"]

    def test_build_compression_prompt_with_existing_compressions(
        self, prompt_builder
    ):
        """Test compression prompt building with existing compressions"""
        queries = [
            {"prompt": "Q3", "response": "A3", "tool_calls": [], "sources": []},
            {"prompt": "Q4", "response": "A4", "tool_calls": [], "sources": []},
        ]

        existing_compressions = [
            {
                "query_index": 1,
                "compressed_summary": "Previous compression summary",
                "timestamp": datetime.now(timezone.utc),
            }
        ]

        messages = prompt_builder.build_prompt(
            queries, existing_compressions
        )

        user_content = messages[1]["content"]

        # Should mention existing compression
        assert "compressed before" in user_content
        assert "Previous compression summary" in user_content
        assert "NEW summary" in user_content

    def test_calculate_conversation_tokens(
        self, sample_conversation
    ):
        """Test conversation token calculation"""
        token_count = TokenCounter.count_conversation_tokens(
            sample_conversation, include_system_prompt=False
        )

        assert token_count > 0

        # With system prompt should be higher
        token_count_with_system = TokenCounter.count_conversation_tokens(
            sample_conversation, include_system_prompt=True
        )

        assert token_count_with_system > token_count

    @patch("application.api.answer.services.compression.threshold_checker.logger")
    def test_error_handling_in_should_compress(
        self, mock_logger, threshold_checker, sample_conversation
    ):
        """Test error handling in should_compress"""
        # Force an error by making get_token_limit raise an exception
        with patch(
            "application.api.answer.services.compression.threshold_checker.get_token_limit",
            side_effect=Exception("Test error"),
        ):
            result = threshold_checker.should_compress(
                sample_conversation, model_id="gpt-4o"
            )

            # Should return False on error
            assert result is False
            # Should log the error
            assert mock_logger.error.called

    @patch("application.api.answer.services.compression.service.logger")
    def test_error_handling_in_get_compressed_context(
        self, mock_logger, compression_service
    ):
        """Test error handling in get_compressed_context"""
        # Malformed conversation
        malformed_conversation = {"queries": None}

        summary, recent = compression_service.get_compressed_context(
            malformed_conversation
        )

        # Should return safe defaults
        assert summary is None
        assert recent == []
        # Should log the error
        assert mock_logger.error.called


    def test_compression_points_array_limiting(self, compression_service):
        """Test that only the most recent compression points are kept"""
        # Simulate a conversation with 3 previous compressions
        conversation = {
            "queries": [
                {"prompt": f"Q{i}", "response": f"A{i}"} for i in range(1, 11)
            ],
            "compression_metadata": {
                "is_compressed": True,
                "last_compression_at": datetime.now(timezone.utc),
                "compression_points": [
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 2,
                        "compressed_summary": "First compression summary",
                        "original_token_count": 100,
                        "compressed_token_count": 20,
                    },
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 5,
                        "compressed_summary": "Second compression summary",
                        "original_token_count": 150,
                        "compressed_token_count": 30,
                    },
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "query_index": 7,
                        "compressed_summary": "Third compression summary",
                        "original_token_count": 200,
                        "compressed_token_count": 40,
                    },
                ],
            },
        }

        # The service should use the most recent compression
        summary, recent = compression_service.get_compressed_context(
            conversation
        )

        # Should use the most recent (third) compression
        assert summary == "Third compression summary"
        assert len(recent) == 2  # Q9 and Q10 (after compression point at index 7)
        assert recent[0]["prompt"] == "Q9"
        assert recent[1]["prompt"] == "Q10"

    def test_compression_with_heavy_tool_usage(self, compression_service):
        """Test compression when conversation has many tool calls with large responses

        Scenario: User asks agent to scrape all files in a GitHub repo, generating
        dozens of tool calls with file contents as responses. This tests the system's
        ability to compress tool-heavy conversations that hit token limits.
        """
        # Simulate a conversation where agent scraped 50 files from DocsGPT repo
        queries = []

        # Initial user request
        queries.append({
            "prompt": "Please analyze all Python files in the https://github.com/arc53/DocsGPT repository",
            "response": "I'll scrape all the Python files from the DocsGPT repository and analyze them.",
            "tool_calls": []
        })

        # Simulate 50 file scraping tool calls with realistic file contents
        file_paths = [
            "application/app.py",
            "application/api/answer/routes.py",
            "application/api/answer/services/conversation_service.py",
            "application/api/answer/services/compression_service.py",
            "application/api/answer/services/stream_processor.py",
            "application/agents/base.py",
            "application/agents/react.py",
            "application/llm/handlers/base.py",
            "application/llm/llm_creator.py",
            "application/core/settings.py",
            "application/core/model_configs.py",
            "application/utils.py",
            "application/vectorstore/base.py",
            "application/parser/file_parser.py",
            "tests/test_compression_service.py",
            "tests/test_agent_token_tracking.py",
            "frontend/src/App.tsx",
            "frontend/src/store/index.ts",
            "deployment/docker-compose.yaml",
            "setup.py",
        ]

        tool_calls = []
        for i, file_path in enumerate(file_paths[:20]):  # First 20 files
            # Each tool call with realistic file content (simulating ~500-1000 tokens per file)
            file_content = f"""
# {file_path}

import os
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime

class {file_path.split('/')[-1].replace('.py', '').title()}:
    '''
    This is a module that handles various operations for the DocsGPT application.
    It contains multiple classes and functions for processing data.
    '''

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.initialized = False
        self.data_store = {{}}

    def process_data(self, input_data: List[str]) -> Dict[str, Any]:
        '''Process input data and return results'''
        results = {{}}
        for item in input_data:
            # Complex processing logic here
            processed = self._transform_item(item)
            results[item] = processed
        return results

    def _transform_item(self, item: str) -> str:
        '''Internal transformation logic'''
        # Multiple lines of transformation code
        transformed = item.upper().strip()
        transformed = transformed.replace(' ', '_')
        return transformed

    def validate_config(self) -> bool:
        '''Validate configuration settings'''
        required_keys = ['api_key', 'endpoint', 'model_id']
        return all(key in self.config for key in required_keys)

# Additional helper functions
def utility_function_one(param: str) -> str:
    return param.strip().lower()

def utility_function_two(data: Dict) -> List:
    return list(data.values())

def main():
    config = {{'api_key': 'test', 'endpoint': 'http://localhost', 'model_id': 'gpt-4'}}
    instance = {file_path.split('/')[-1].replace('.py', '').title()}(config)
    instance.process_data(['item1', 'item2', 'item3'])
""" * 2  # Double it to simulate ~1000-1500 tokens per response

            tool_calls.append({
                "call_id": f"call_{i}",
                "tool_name": "github_file_scraper",
                "action_name": "read_file",
                "arguments": {"file_path": file_path},
                "result": {"content": file_content, "status": "success"},
                "status": "success"
            })

        # Add query with all tool calls
        queries.append({
            "prompt": "[Agent continues processing]",
            "response": "I've scraped 20 Python files. Let me analyze the patterns...",
            "tool_calls": tool_calls
        })

        # Add analysis response
        queries.append({
            "prompt": "[Agent continues analysis]",
            "response": """Based on my analysis of the 20 Python files:

1. Architecture: The codebase follows a modular architecture with clear separation between API, agents, LLM handlers, and utilities.

2. Key patterns identified:
   - Heavy use of type hints (typing module)
   - Consistent error handling patterns
   - Service-based architecture for API endpoints
   - Factory pattern for LLM creation
   - Abstract base classes for extensibility

3. Core components:
   - Agent system with tool integration
   - LLM provider abstraction
   - Compression service for context management
   - Stream processing for real-time responses

4. Code quality observations:
   - Comprehensive docstrings
   - Good test coverage
   - Clear naming conventions
   - Proper separation of concerns""",
            "tool_calls": []
        })

        conversation = {"queries": queries}

        # Mock LLM response for compression
        mock_summary = """<summary>
        User requested analysis of all Python files in DocsGPT GitHub repository.
        Agent scraped 20 files including app.py, API routes, services, agents, and tests.
        Analysis revealed modular architecture with service-based design, type hints,
        factory patterns, and agent system with tool integration. Code quality is high
        with comprehensive docstrings and test coverage.
        </summary>"""
        compression_service.llm.gen.return_value = mock_summary

        # Compress the heavy tool usage
        result = compression_service.compress_conversation(
            conversation=conversation,
            compress_up_to_index=1  # Compress first 2 queries (including all tool calls)
        )

        # Verify compression handled tool calls properly
        assert result.query_index == 1
        assert result.compressed_summary is not None

        # Verify the compression prompt included tool call information
        call_args = compression_service.llm.gen.call_args
        messages = call_args[1]["messages"]
        user_message = messages[1]["content"]

        # Should include tool calls section
        assert "Tool Calls:" in user_message
        assert "github_file_scraper" in user_message

        # Verify compression ratio (should be significant with all that tool data)
        original_tokens = result.original_token_count
        compressed_tokens = result.compressed_token_count
        compression_ratio = result.compression_ratio

        # With 20 large tool responses, original should be substantial
        assert original_tokens > 5000  # At least 5k tokens from tool responses
        assert compressed_tokens < 500  # Summary should be much smaller
        assert compression_ratio > 10  # Should achieve >10x compression

    def test_compression_with_needle_in_haystack(self, compression_service):
        """Test compression preserves important information buried in long conversation

        Scenario: User has long conversation with verbose responses, hiding critical
        information in the middle. Tests that compression correctly identifies and
        preserves key details even when surrounded by lengthy content.
        """
        # Create a long conversation with important info buried in the middle
        queries = []

        # Query 1: Long general discussion
        queries.append({
            "prompt": "Tell me about Python programming best practices",
            "response": """Python best practices encompass a wide range of principles and patterns.
Let me provide a comprehensive overview:

1. Code Style and Formatting:
   - Follow PEP 8 style guide for consistent formatting
   - Use 4 spaces for indentation (not tabs)
   - Limit lines to 79 characters for code, 72 for docstrings
   - Use meaningful variable names that describe their purpose
   - Add whitespace around operators and after commas
   - Group imports: standard library, third-party, local

2. Documentation:
   - Write clear docstrings for all functions, classes, and modules
   - Use type hints for better code clarity and IDE support
   - Include examples in docstrings when helpful
   - Keep comments up-to-date with code changes

3. Error Handling:
   - Use specific exceptions rather than bare except clauses
   - Create custom exceptions for domain-specific errors
   - Always clean up resources with context managers (with statement)
   - Log errors appropriately for debugging

4. Testing:
   - Write unit tests for all critical functionality
   - Aim for high test coverage (80%+)
   - Use pytest for modern testing features
   - Mock external dependencies in tests

5. Code Organization:
   - Keep functions small and focused on single tasks
   - Use classes to group related functionality
   - Avoid deep nesting (max 3-4 levels)
   - Extract complex conditions into well-named variables

6. Performance:
   - Use list comprehensions for simple transformations
   - Avoid premature optimization
   - Profile code before optimizing
   - Use generators for large datasets

These practices help maintain readable, maintainable, and efficient code.""",
            "tool_calls": []
        })

        # Query 2: Another long response
        queries.append({
            "prompt": "What about Python data structures?",
            "response": """Python provides several built-in data structures, each optimized for different use cases:

1. Lists:
   - Ordered, mutable sequences
   - Dynamic sizing with amortized O(1) append
   - Access by index in O(1)
   - Insertion/deletion in middle is O(n)
   - Use cases: ordered collections, stacks, queues
   - Methods: append(), extend(), insert(), remove(), pop(), sort()

2. Tuples:
   - Ordered, immutable sequences
   - Slightly more memory efficient than lists
   - Can be used as dictionary keys (if contents are hashable)
   - Use cases: fixed collections, function return values, dictionary keys

3. Dictionaries:
   - Unordered (ordered in Python 3.7+) key-value mappings
   - Average O(1) lookup, insertion, deletion
   - Keys must be hashable
   - Use cases: lookups, caching, counting, grouping
   - Methods: get(), keys(), values(), items(), update(), pop()

4. Sets:
   - Unordered collections of unique elements
   - Average O(1) membership testing
   - Efficient for removing duplicates
   - Support set operations: union, intersection, difference
   - Use cases: membership testing, removing duplicates, set mathematics

5. Collections module extensions:
   - defaultdict: dict with default values for missing keys
   - Counter: dict subclass for counting hashable objects
   - deque: double-ended queue with O(1) append/pop from both ends
   - OrderedDict: maintains insertion order (less relevant in Python 3.7+)
   - namedtuple: tuple subclass with named fields

6. Performance considerations:
   - Lists for ordered data with frequent append operations
   - Dictionaries for key-based lookups
   - Sets for membership testing and uniqueness
   - Deques for queue operations from both ends
   - Tuples for immutable data

Understanding these data structures is crucial for writing efficient Python code.""",
            "tool_calls": []
        })

        # Query 3: THE CRITICAL INFORMATION (needle in the haystack)
        queries.append({
            "prompt": "I need to remember this important detail",
            "response": """I'll make a note of that important detail.

CRITICAL INFORMATION TO REMEMBER:
The production database password is stored in the environment variable DB_PASSWORD_PROD.
The backup schedule is set to run daily at 3:00 AM UTC.
The API rate limit for premium users is 10,000 requests per hour.
The encryption key rotation happens every 90 days.
The primary contact for incidents is: ops-team@example.com

I've recorded this information for our conversation. These operational details are important for system administration and should be referenced when needed.""",
            "tool_calls": []
        })

        # Query 4: More long content after the important info
        queries.append({
            "prompt": "Explain Python decorators in detail",
            "response": """Python decorators are a powerful feature that allows you to modify or enhance functions and classes. Here's a comprehensive explanation:

1. Basic Concept:
   - Decorators are functions that take another function as input
   - They return a modified version of that function
   - Syntax: @decorator above function definition
   - They implement the decorator design pattern

2. Function Decorators:
   ```python
   def my_decorator(func):
       def wrapper(*args, **kwargs):
           # Code before function
           result = func(*args, **kwargs)
           # Code after function
           return result
       return wrapper

   @my_decorator
   def my_function():
       pass
   ```

3. Common Use Cases:
   - Logging: Record function calls and results
   - Timing: Measure execution time
   - Authentication: Check permissions before execution
   - Caching: Store and return cached results
   - Validation: Check input parameters
   - Rate limiting: Throttle function calls

4. Decorators with Arguments:
   ```python
   def repeat(times):
       def decorator(func):
           def wrapper(*args, **kwargs):
               for _ in range(times):
                   result = func(*args, **kwargs)
               return result
           return wrapper
       return decorator

   @repeat(3)
   def greet():
       print("Hello")
   ```

5. Class Decorators:
   - Can decorate entire classes
   - Useful for adding methods or attributes
   - Can enforce patterns like singleton

6. Built-in Decorators:
   - @property: Create managed attributes
   - @staticmethod: Define static methods
   - @classmethod: Define class methods
   - @abstractmethod: Define abstract methods

7. functools.wraps:
   - Preserves original function metadata
   - Should be used in decorator implementations
   - Maintains __name__, __doc__, etc.

8. Practical Examples:
   - @login_required for web routes
   - @cache for memoization
   - @retry for resilient API calls
   - @deprecated for marking old code

Decorators are essential for writing clean, maintainable Python code with separation of concerns.""",
            "tool_calls": []
        })

        # Query 5: Final long response
        queries.append({
            "prompt": "What about Python async programming?",
            "response": """Asynchronous programming in Python allows for concurrent execution of I/O-bound operations:

1. Core Concepts:
   - Event loop: Manages and executes async tasks
   - Coroutines: Functions defined with async def
   - await: Pauses coroutine until awaitable completes
   - Tasks: Wrapper for coroutines to run concurrently

2. Basic Syntax:
   ```python
   import asyncio

   async def fetch_data():
       await asyncio.sleep(1)
       return "data"

   async def main():
       result = await fetch_data()
       print(result)

   asyncio.run(main())
   ```

3. When to Use Async:
   - I/O-bound operations (network requests, file I/O, database queries)
   - Multiple concurrent operations
   - Real-time applications (websockets, streaming)
   - NOT for CPU-bound tasks (use multiprocessing instead)

4. Common Patterns:
   - Gather: Run multiple coroutines concurrently
   - create_task: Schedule coroutine execution
   - Semaphore: Limit concurrent operations
   - Queue: Producer-consumer patterns

5. Async Libraries:
   - aiohttp: Async HTTP client/server
   - asyncpg: Async PostgreSQL driver
   - motor: Async MongoDB driver
   - aioredis: Async Redis client

6. Error Handling:
   - Use try/except in coroutines
   - Tasks can be cancelled with task.cancel()
   - Timeouts with asyncio.wait_for()

Understanding async programming is crucial for building scalable Python applications.""",
            "tool_calls": []
        })

        conversation = {"queries": queries}

        # Mock LLM response that MUST preserve the critical information
        mock_summary = """<summary>
        User asked about Python best practices, data structures, decorators, and async programming.
        Discussed code style, testing, documentation standards, and various Python data structures.

        CRITICAL OPERATIONAL DETAILS PROVIDED:
        - Production database password stored in DB_PASSWORD_PROD environment variable
        - Backup schedule: daily at 3:00 AM UTC
        - Premium API rate limit: 10,000 requests/hour
        - Encryption key rotation: every 90 days
        - Incident contact: ops-team@example.com

        Also covered decorators for code enhancement and async programming for I/O-bound operations.
        </summary>"""
        compression_service.llm.gen.return_value = mock_summary

        # Compress everything except the last query
        result = compression_service.compress_conversation(
            conversation=conversation,
            compress_up_to_index=3  # Compress first 4 queries (includes the critical info)
        )

        # Verify compression happened
        assert result.query_index == 3
        assert result.compressed_summary is not None

        # Get the compressed context
        conversation["compression_metadata"] = {
            "is_compressed": True,
            "last_compression_at": datetime.now(timezone.utc),
            "compression_points": [result.to_dict()]
        }

        summary, recent = compression_service.get_compressed_context(
            conversation
        )

        # Verify critical information is in the summary
        assert summary is not None
        assert "DB_PASSWORD_PROD" in summary or "database password" in summary.lower()
        assert "3:00 AM UTC" in summary or "backup" in summary.lower()
        assert "10,000" in summary or "rate limit" in summary.lower()
        assert "ops-team@example.com" in summary or "incident contact" in summary.lower()

        # Verify only the last query is in recent
        assert len(recent) == 1
        assert "async programming" in recent[0]["prompt"].lower()

        # The compression should be substantial (long responses compressed to summary)
        assert result.original_token_count > 1300  # 4 long responses
        assert result.compressed_token_count < 300  # Summary should be concise
        assert result.compression_ratio > 4  # At least 4x compression


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
