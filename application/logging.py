import datetime
import functools
import inspect
import time

import logging
import uuid
from typing import Any, Callable, Dict, Generator, List

from application.core import log_context
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
            agent_id = getattr(args[0], "agent_id", None) or kwargs.get("agent_id")
            conversation_id = (
                kwargs.get("conversation_id")
                or getattr(args[0], "conversation_id", None)
            )
            model = getattr(args[0], "gpt_model", None) or getattr(args[0], "model", None)

            # Capture the surrounding activity_id before overlaying ours,
            # so nested activities record the parent → child link.
            parent_activity_id = log_context.snapshot().get("activity_id")

            context = LogContext(endpoint, activity_id, user, api_key, query)
            kwargs["log_context"] = context

            ctx_token = log_context.bind(
                activity_id=activity_id,
                parent_activity_id=parent_activity_id,
                user_id=user,
                agent_id=agent_id,
                conversation_id=conversation_id,
                endpoint=endpoint,
                model=model,
            )

            started_at = time.monotonic()
            logging.info(
                "activity_started",
                extra={
                    "activity_id": activity_id,
                    "parent_activity_id": parent_activity_id,
                    "user_id": user,
                    "agent_id": agent_id,
                    "conversation_id": conversation_id,
                    "endpoint": endpoint,
                    "model": model,
                },
            )

            error: BaseException | None = None
            try:
                generator = func(*args, **kwargs)
                yield from _consume_and_log(generator, context)
            except Exception as exc:
                # Only ``Exception`` counts as an activity error; ``GeneratorExit``
                # (consumer disconnected mid-stream) and ``KeyboardInterrupt``
                # flow through the finally as ``status="ok"``, matching
                # ``_consume_and_log``.
                error = exc
                raise
            finally:
                _emit_activity_finished(
                    activity_id=activity_id,
                    parent_activity_id=parent_activity_id,
                    user=user,
                    endpoint=endpoint,
                    started_at=started_at,
                    error=error,
                )
                log_context.reset(ctx_token)

        return wrapper

    return decorator


def _emit_activity_finished(
    *,
    activity_id: str,
    parent_activity_id: str | None,
    user: str,
    endpoint: str,
    started_at: float,
    error: BaseException | None,
) -> None:
    """Emit the paired ``activity_finished`` event with duration and outcome."""
    duration_ms = int((time.monotonic() - started_at) * 1000)
    logging.info(
        "activity_finished",
        extra={
            "activity_id": activity_id,
            "parent_activity_id": parent_activity_id,
            "user_id": user,
            "endpoint": endpoint,
            "duration_ms": duration_ms,
            "status": "error" if error is not None else "ok",
            "error_class": type(error).__name__ if error is not None else None,
        },
    )


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
