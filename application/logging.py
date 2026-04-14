import datetime
import functools
import inspect

import logging
import uuid
from typing import Any, Callable, Dict, Generator, List

from application.storage.db.repositories.stack_logs import StackLogsRepository
from application.storage.db.session import db_session

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class LogContext:
    def __init__(self, endpoint, activity_id, user, api_key, query):
        self.endpoint = endpoint
        self.activity_id = activity_id
        self.user = user
        self.api_key = api_key
        self.query = query
        self.stacks = []


def build_stack_data(
    obj: Any,
    include_attributes: List[str] = None,
    exclude_attributes: List[str] = None,
    custom_data: Dict = None,
) -> Dict:
    if obj is None:
        raise ValueError("The 'obj' parameter cannot be None")
    data = {}
    if include_attributes is None:
        include_attributes = []
        for name, value in inspect.getmembers(obj):
            if (
                not name.startswith("_")
                and not inspect.ismethod(value)
                and not inspect.isfunction(value)
            ):
                include_attributes.append(name)
    for attr_name in include_attributes:
        if exclude_attributes and attr_name in exclude_attributes:
            continue
        try:
            attr_value = getattr(obj, attr_name)
            if attr_value is not None:
                if isinstance(attr_value, (int, float, str, bool)):
                    data[attr_name] = attr_value
                elif isinstance(attr_value, list):
                    if all(isinstance(item, dict) for item in attr_value):
                        data[attr_name] = attr_value
                    elif all(hasattr(item, "__dict__") for item in attr_value):
                        data[attr_name] = [item.__dict__ for item in attr_value]
                    else:
                        data[attr_name] = [str(item) for item in attr_value]
                elif isinstance(attr_value, dict):
                    data[attr_name] = {k: str(v) for k, v in attr_value.items()}
        except AttributeError as e:
            logging.warning(f"AttributeError while accessing {attr_name}: {e}")
        except AttributeError:
            pass
    if custom_data:
        data.update(custom_data)
    return data


def log_activity() -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            activity_id = str(uuid.uuid4())
            data = build_stack_data(args[0])
            endpoint = data.get("endpoint", "")
            user = data.get("user", "local")
            api_key = data.get("user_api_key", "")
            query = kwargs.get("query", getattr(args[0], "query", ""))

            context = LogContext(endpoint, activity_id, user, api_key, query)
            kwargs["log_context"] = context

            logging.info(
                f"Starting activity: {endpoint} - {activity_id} - User: {user}"
            )

            generator = func(*args, **kwargs)
            yield from _consume_and_log(generator, context)

        return wrapper

    return decorator


def _consume_and_log(generator: Generator, context: "LogContext"):
    try:
        for item in generator:
            yield item
    except Exception as e:
        logging.exception(f"Error in {context.endpoint} - {context.activity_id}: {e}")
        context.stacks.append({"component": "error", "data": {"message": str(e)}})
        _log_activity_to_db(
            endpoint=context.endpoint,
            activity_id=context.activity_id,
            user=context.user,
            api_key=context.api_key,
            query=context.query,
            stacks=context.stacks,
            level="error",
        )
        raise
    finally:
        _log_activity_to_db(
            endpoint=context.endpoint,
            activity_id=context.activity_id,
            user=context.user,
            api_key=context.api_key,
            query=context.query,
            stacks=context.stacks,
            level="info",
        )


def _log_activity_to_db(
    endpoint: str,
    activity_id: str,
    user: str,
    api_key: str,
    query: str,
    stacks: List[Dict],
    level: str,
) -> None:
    """Append a per-request activity log row to Postgres (``stack_logs``)."""
    try:
        # Clean up text fields to be no longer than 10000 characters so a
        # runaway payload can't blow up the insert.
        def _truncate(val):
            if isinstance(val, str) and len(val) > 10000:
                return val[:10000]
            return val

        with db_session() as conn:
            StackLogsRepository(conn).insert(
                activity_id=activity_id,
                endpoint=_truncate(endpoint),
                level=_truncate(level),
                user_id=_truncate(user),
                api_key=_truncate(api_key),
                query=_truncate(query),
                stacks=stacks,
                timestamp=datetime.datetime.now(datetime.timezone.utc),
            )
        logging.debug(f"Logged activity to Postgres: {activity_id}")
    except Exception as e:
        logging.error(f"Failed to log activity to Postgres: {e}", exc_info=True)
