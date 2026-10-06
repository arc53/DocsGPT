"""Background jobs: slow tool calls a turn hands off, and the turns that resume a conversation.

A server-side tool call in a chat turn runs in a bounded per-process pool
(:mod:`docsgpt.background.pool`). The turn waits up to
``BACKGROUND_YIELD_SECONDS``; a call still running then becomes a
``background_jobs`` row (:mod:`docsgpt.background.handoff`) and the model gets
a ``running`` result with the job id instead of the tool's result. The job
finishes in the same thread (``inprocess``), in a Celery worker (``celery``),
or as a detached sandbox command a Celery poller follows (``sandbox``).

A finished job resumes its conversation (:mod:`docsgpt.background.wake`): a
headless continuation turn answers in the same conversation, unless
``check_job`` or the user's next message took the result first.
"""
