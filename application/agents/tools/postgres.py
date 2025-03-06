import psycopg2
from application.agents.tools.base import Tool

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

        if action_name in actions:
            return actions[action_name](**kwargs)
        else:
            raise ValueError(f"Unknown action: {action_name}")

    def _execute_sql(self, sql_query):
        """
        Executes an SQL query against the PostgreSQL database using a connection string.
        """
        conn = None  # Initialize conn to None for error handling
        try:
            conn = psycopg2.connect(self.connection_string)
            cur = conn.cursor()
            cur.execute(sql_query)
            conn.commit()

            if sql_query.strip().lower().startswith("select"):
                column_names = [desc[0] for desc in cur.description] if cur.description else []
                results = []
                rows = cur.fetchall()
                for row in rows:
                    results.append(dict(zip(column_names, row)))
                response_data = {"data": results, "column_names": column_names}
            else:
                row_count = cur.rowcount
                response_data = {"message": f"Query executed successfully, {row_count} rows affected."}

            cur.close()
            return {
                "status_code": 200,
                "message": "SQL query executed successfully.",
                "response_data": response_data,
            }

        except psycopg2.Error as e:
            error_message = f"Database error: {e}"
            print(f"Database error: {e}")
            return {
                "status_code": 500,
                "message": "Failed to execute SQL query.",
                "error": error_message,
            }
        finally:
            if conn:  # Ensure connection is closed even if errors occur
                conn.close()

    def _get_schema(self, db_name):
        """
        Retrieves the schema of the PostgreSQL database using a connection string.
        """
        conn = None # Initialize conn to None for error handling
        try:
            conn = psycopg2.connect(self.connection_string)
            cur = conn.cursor()

            cur.execute("""
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
            """)

            schema_data = {}
            for row in cur.fetchall():
                table_name, column_name, data_type, column_default, is_nullable = row
                if table_name not in schema_data:
                    schema_data[table_name] = []
                schema_data[table_name].append({
                    "column_name": column_name,
                    "data_type": data_type,
                    "column_default": column_default,
                    "is_nullable": is_nullable
                })

            cur.close()
            return {
                "status_code": 200,
                "message": "Database schema retrieved successfully.",
                "schema": schema_data,
            }

        except psycopg2.Error as e:
            error_message = f"Database error: {e}"
            print(f"Database error: {e}")
            return {
                "status_code": 500,
                "message": "Failed to retrieve database schema.",
                "error": error_message,
            }
        finally:
            if conn: # Ensure connection is closed even if errors occur
                conn.close()

    def get_actions_metadata(self):
        return [
            {
                "name": "postgres_execute_sql",
                "description": "Execute an SQL query against the PostgreSQL database and return the results. Use this tool to interact with the database, e.g., retrieve specific data or perform updates. Only SELECT queries will return data, other queries will return execution status.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql_query": {
                            "type": "string",
                            "description": "The SQL query to execute.",
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
                "description": "PostgreSQL database connection string (e.g., 'postgresql://user:password@host:port/dbname')",
            },
        }