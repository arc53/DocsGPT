import logging
import re

import psycopg2

from application.agents.tools.base import Tool

logger = logging.getLogger(__name__)

# SQL statements that are safe for read-only execution.
_ALLOWED_STATEMENT_PREFIXES = ("select", "explain", "with")

# Pattern to strip leading SQL block comments (/* ... */) and whitespace.
_LEADING_COMMENT_RE = re.compile(r"^(\s*/\*.*?\*/\s*)*", re.DOTALL | re.IGNORECASE)

# Keywords that must NOT appear anywhere in the query body (case-insensitive).
# This catches writable CTEs like ``WITH ... INSERT ... RETURNING``.
_FORBIDDEN_KEYWORDS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE)\b",
    re.IGNORECASE,
)


class PostgresTool(Tool):
    """
    PostgreSQL Database Tool
    A tool for connecting to a PostgreSQL database using a connection string,
    executing SQL queries, and retrieving schema information.
    """

    def __init__(self, config):
        self.config = config
        self.connection_string = config.get("token", "")

    def execute_action(self, action_name, **kwargs):
        actions = {
            "postgres_execute_sql": self._execute_sql,
            "postgres_get_schema": self._get_schema,
        }
        if action_name not in actions:
            raise ValueError(f"Unknown action: {action_name}")
        return actions[action_name](**kwargs)

    @staticmethod
    def _validate_sql_query(sql_query: str) -> str | None:
        """Return an error message if *sql_query* is not a safe read-only query, else ``None``."""
        # Strip leading block comments so they cannot hide the real statement.
        cleaned = _LEADING_COMMENT_RE.sub("", sql_query).strip()

        # Reject empty queries.
        if not cleaned:
            return "Empty SQL query."

        # Reject stacked statements (multiple queries separated by ';').
        # Allow a single trailing semicolon but nothing after it.
        stripped_semi = cleaned.rstrip(";").strip()
        if ";" in stripped_semi:
            return "Multiple SQL statements are not allowed."

        # Only allow read-only statement types.
        first_word = cleaned.split()[0].lower() if cleaned.split() else ""
        if first_word not in _ALLOWED_STATEMENT_PREFIXES:
            return f"Only SELECT queries are allowed. Got: {first_word.upper()}"

        # Even inside CTEs, forbid mutating keywords.
        if _FORBIDDEN_KEYWORDS_RE.search(cleaned):
            return "Query contains forbidden SQL keyword."

        return None

    def _execute_sql(self, sql_query):
        """
        Executes a **read-only** SQL query against the PostgreSQL database.

        Only SELECT (and EXPLAIN / WITH … SELECT) queries are permitted.
        Mutating statements are rejected before any database connection is made.
        """
        validation_error = self._validate_sql_query(sql_query)
        if validation_error:
            logger.warning("PostgreSQL query blocked: %s — query: %s", validation_error, sql_query[:200])
            return {
                "status_code": 403,
                "message": "Query not allowed.",
                "error": validation_error,
            }

        conn = None
        try:
            conn = psycopg2.connect(self.connection_string)
            cur = conn.cursor()
            cur.execute(sql_query)

            column_names = (
                [desc[0] for desc in cur.description] if cur.description else []
            )
            results = []
            rows = cur.fetchall()
            for row in rows:
                results.append(dict(zip(column_names, row)))
            response_data = {"data": results, "column_names": column_names}

            cur.close()
            return {
                "status_code": 200,
                "message": "SQL query executed successfully.",
                "response_data": response_data,
            }

        except psycopg2.Error as e:
            error_message = f"Database error: {e}"
            logger.error("PostgreSQL execute_sql error: %s", e)
            return {
                "status_code": 500,
                "message": "Failed to execute SQL query.",
                "error": error_message,
            }
        finally:
            if conn:
                conn.close()

    def _get_schema(self, db_name):
        """
        Retrieves the schema of the PostgreSQL database using a connection string.
        """
        conn = None
        try:
            conn = psycopg2.connect(self.connection_string)
            cur = conn.cursor()

            cur.execute(
                """
                SELECT
                    table_name,
                    column_name,
                    data_type,
                    column_default,
                    is_nullable
                FROM
                    information_schema.columns
                WHERE
                    table_schema = 'public'
                ORDER BY
                    table_name,
                    ordinal_position;
            """
            )

            schema_data = {}
            for row in cur.fetchall():
                table_name, column_name, data_type, column_default, is_nullable = row
                if table_name not in schema_data:
                    schema_data[table_name] = []
                schema_data[table_name].append(
                    {
                        "column_name": column_name,
                        "data_type": data_type,
                        "column_default": column_default,
                        "is_nullable": is_nullable,
                    }
                )

            cur.close()
            return {
                "status_code": 200,
                "message": "Database schema retrieved successfully.",
                "schema": schema_data,
            }

        except psycopg2.Error as e:
            error_message = f"Database error: {e}"
            logger.error("PostgreSQL get_schema error: %s", e)
            return {
                "status_code": 500,
                "message": "Failed to retrieve database schema.",
                "error": error_message,
            }
        finally:
            if conn:
                conn.close()

    def get_actions_metadata(self):
        return [
            {
                "name": "postgres_execute_sql",
                "description": "Execute a read-only SQL query against the PostgreSQL database and return the results. Only SELECT queries are allowed; mutating statements (INSERT, UPDATE, DELETE, DROP, etc.) are rejected.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": "The SQL SELECT query to execute.",
                        },
                    },
                    "required": ["sql_query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "postgres_get_schema",
                "description": "Retrieve the schema of the PostgreSQL database, including tables and their columns. Use this to understand the database structure before executing queries. db_name is 'default' if not provided.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "db_name": {
                            "type": "string",
                            "description": "The name of the database to retrieve the schema for.",
                        },
                    },
                    "required": ["db_name"],
                    "additionalProperties": False,
                },
            },
        ]

    def get_config_requirements(self):
        return {
            "token": {
                "type": "string",
                "label": "Connection String",
                "description": "PostgreSQL database connection string",
                "required": True,
                "secret": True,
                "order": 1,
            },
        }
