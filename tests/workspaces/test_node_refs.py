"""The node ref transformer: a caller's retention policy decides what an agent node keeps when its workflow
changes hands; the transformer applies it the same way for every caller."""

from __future__ import annotations

from docsgpt.workspaces.node_refs import NodeRetention, node_transform, retain_node_refs


def _retention(**overrides) -> NodeRetention:
    kept = {"t-keep", "s-keep", "m-keep", "t-new", "s-new", "m-new"}
    fields = {
        "keep_tool": lambda v: v in kept,
        "keep_source": lambda v: v in kept,
        "keep_folders": lambda folders: [f for f in folders if f == "f-keep"],
        "keep_model": lambda v: v in kept,
    }
    fields.update(overrides)
    return NodeRetention(**fields)


class TestRetainNodeRefs:
    def test_only_agent_nodes_change(self):
        config = {"tools": ["t-drop"], "model_id": "m-drop"}
        assert retain_node_refs("start", config, _retention()) == {"tools": ["t-drop"], "model_id": "m-drop"}

    def test_kept_refs_keep_their_order_and_the_rest_go(self):
        config = {"tools": ["t-drop", "t-keep", None, ""], "sources": ["s-keep", "s-drop"],
                  "folders": ["f-drop", "f-keep"], "model_id": "m-drop"}
        assert retain_node_refs("agent", config, _retention()) == {
            "tools": ["t-keep"], "sources": ["s-keep"], "folders": ["f-keep"], "model_id": None,
        }

    def test_a_single_ref_is_read_as_a_list(self):
        config = {"sources": "s-keep", "folders": "f-keep"}
        assert retain_node_refs("agent", config, _retention()) == {"sources": ["s-keep"], "folders": ["f-keep"]}

    def test_empty_fields_stay_as_they_are(self):
        config = {"tools": [], "sources": None, "model_id": ""}
        assert retain_node_refs("agent", config, _retention()) == {"tools": [], "sources": None, "model_id": ""}

    def test_refs_are_resolved_before_they_are_checked(self):
        swaps = {("tool", "t-old"): "t-new", ("source", "s-old"): "s-new", ("model", "m-old"): "m-new"}
        retention = _retention(resolve=lambda kind, value: swaps.get((kind, value), value))
        config = {"tools": ["t-old", "t-keep"], "sources": ["s-old"], "model_id": "m-old"}
        assert retain_node_refs("agent", config, retention) == {
            "tools": ["t-new", "t-keep"], "sources": ["s-new"], "model_id": "m-new",
        }

    def test_nested_settings_drop_their_flat_leftovers(self):
        config = {"config": {"tools": ["t-keep"]}, "tools": ["t-drop"], "sources": ["s-keep"], "title": "x"}
        assert node_transform(_retention())("agent", config) == {"config": {"tools": ["t-keep"]}, "title": "x"}
