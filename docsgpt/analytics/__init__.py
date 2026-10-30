"""Conversation analytics: labels the decision model gives stored conversations, written in the background.

``schema`` and ``derive`` are ported from arc-decide (``arcd/analytics/``, MIT): the questions, state builders and
published rules the model was trained and evaluated with. ``states`` builds those states from stored message rows,
``topics`` the per-agent topic lists, and ``tasks`` runs the sweep that labels conversations into
``conversation_labels``. Nothing here runs in the request path, and no worker loads a model.
"""
