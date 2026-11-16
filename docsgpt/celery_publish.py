"""The Celery app class: Celery, with a publish that survives kombu closing the channel under it.

kombu 5.5.0 to 5.7.0 lose a message when the broker connection drops during the queue declare that
precedes a publish (celery/kombu#2804). The declare's own retry reconnects and succeeds, but it closes
the channel the producer already holds, and the publish then runs on that closed channel. On the Redis
transport it raises ``AttributeError: 'NoneType' object has no attribute 'client'``. Nothing has been
sent, and kombu's retry policy does not cover an ``AttributeError``, so ``apply_async`` fails.

The connection is already back by then, so sending once more goes through. Remove this module when kombu
ships the fix.
"""

import logging
import os
from typing import Any, Optional

from celery import Celery as _Celery
from kombu.utils.uuid import uuid

logger = logging.getLogger(__name__)

_KOMBU = f"{os.sep}kombu{os.sep}"


def _raised_inside_kombu(exc: BaseException) -> bool:
    """Whether ``exc`` came out of kombu's own code, not out of a task, a signal handler or Celery."""
    tb = exc.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    return _KOMBU in tb.tb_frame.f_code.co_filename


class Celery(_Celery):
    """Celery whose ``send_task`` sends again when kombu published on a channel it had closed."""

    def send_task(
        self,
        name: str,
        args: Any = None,
        kwargs: Any = None,
        countdown: Any = None,
        eta: Any = None,
        task_id: Optional[str] = None,
        **options: Any,
    ) -> Any:
        """Send a task message, once more if kombu lost the first to a reconnect during the declare.

        Args:
            name: Task name.
            args: Positional arguments of the task.
            kwargs: Keyword arguments of the task.
            countdown: Seconds to wait before the task runs.
            eta: When the task runs.
            task_id: Id of the task. One is made here when absent, so both attempts carry the same id.
            **options: Everything else ``Celery.send_task`` takes.

        Returns:
            The task's ``AsyncResult``.
        """
        task_id = task_id or uuid()
        try:
            return super().send_task(name, args, kwargs, countdown, eta, task_id=task_id, **options)
        except AttributeError as exc:
            if not _raised_inside_kombu(exc):
                raise
            logger.warning(
                "Publishing %s[%s] failed on a channel kombu had closed (%s); sending it again", name, task_id, exc
            )
        return super().send_task(name, args, kwargs, countdown, eta, task_id=task_id, **options)
