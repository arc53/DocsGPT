"""Build /v1/chat/completions request bodies shaped like the V1-01..V1-05 scenarios.

The builder reads files written by ``generate.generate_scenario`` and returns a
list of steps, each with a ready-to-send OpenAI-style ``body``. Two payload
styles are supported, matching what the real client did:

* ``text``: the client pastes its own extraction into the user message as
  ``[Priloga <name>: <status>]`` + ``--- Začetek besedila: <name> ---`` ...
  ``--- Konec besedila ---`` blocks and re-sends every earlier file each turn.
* ``file_parts``: the same files as base64 ``file`` parts (PDF/DOCX, upper-case
  ``.PDF`` names kept as sent) and ``image_url`` data-URI parts.

The bodies never carry a conversation id: an end-to-end script threads state
itself (for example by putting ``{"docsgpt": {"conversation_id": ...}}`` into
``extra_body`` once the first response returns one). Example::

    from tests.fixtures.many_attachments import generate as gen, v1_requests as v1

    gen.generate_scenario("V1-01", out)
    for step in v1.build_requests("V1-01", out, payload="file_parts"):
        resp = client.post("/v1/chat/completions", json=step["body"], headers=auth)
"""

from __future__ import annotations

import base64
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from tests.fixtures.many_attachments import corpus
from tests.fixtures.many_attachments import generate as gen

SYSTEM_PROMPT = (
    "Si pravni asistent za nepremičninsko pravo (fiktivna testna namestitev). Odgovarjaj v slovenščini, "
    "navajaj člene in priloge, ki jih uporabiš. Za iskanje predpisov uporabi orodji search in get_by_id."
)

CLIENT_TOOLS: Dict[str, Dict[str, Any]] = {
    "search": {"type": "function", "function": {
        "name": "search", "description": "Search the (fictional) statute database by free text.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    "get_by_id": {"type": "function", "function": {
        "name": "get_by_id", "description": "Fetch one statute article by its id.",
        "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}}},
    "create_artefact": {"type": "function", "function": {
        "name": "create_artefact", "description": "Create a draft document in the client app.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["title", "content"]}}},
    "str_replace_editor": {"type": "function", "function": {
        "name": "str_replace_editor", "description": "View or edit a draft in the client app.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string", "enum": ["view", "create", "str_replace", "insert"]},
            "path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}},
            "required": ["command", "path"]}}},
}


def client_tools(names: List[str]) -> List[Dict[str, Any]]:
    """Return OpenAI tool definitions for the named client tools."""
    return [CLIENT_TOOLS[n] for n in names]


def _entry_text(sdir: Path, entry: Dict[str, Any]) -> Optional[str]:
    tp = entry.get("text_path")
    return (sdir / tp).read_text(encoding="utf-8") if tp else None


def text_block(entry: Dict[str, Any], text: Optional[str]) -> str:
    """Format one pasted attachment the way the legal client does."""
    name = entry["name"]
    if entry["kind"] in gen.IMAGE_KINDS:
        return f"[Priloga {name}: slikovna priloga, besedilo ni na voljo.]"
    if entry.get("text_kind") == "ocr":
        status = f"skeniran dokument ({entry.get('pages', 1)} strani), besedilo prepoznano z OCR."
    else:
        status = "vključeno je besedilo dokumenta."
    return (f"[Priloga {name}: {status}]\n--- Začetek besedila: {name} ---\n{text or ''}\n"
            "--- Konec besedila ---")


def file_part(sdir: Path, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return an OpenAI content part carrying the file as base64."""
    data = base64.b64encode((sdir / entry["path"]).read_bytes()).decode()
    if entry["kind"] in gen.IMAGE_KINDS:
        return {"type": "image_url", "image_url": {"url": f"data:{entry['mime']};base64,{data}"}}
    return {"type": "file", "file": {"filename": entry["name"], "file_data": f"data:{entry['mime']};base64,{data}"}}


def _user_content(sdir: Path, entries: List[Dict[str, Any]], prompt: str, payload: str) -> Any:
    if payload == "text":
        blocks = [text_block(e, _entry_text(sdir, e)) for e in entries]
        return "\n\n".join([prompt, *blocks])
    return [{"type": "text", "text": prompt}, *[file_part(sdir, e) for e in entries]]


def _tool_round(rng: random.Random, r: int, chars: List[int]) -> List[Dict[str, Any]]:
    name = "search" if r % 2 == 0 else "get_by_id"
    args = '{"query": "namenska raba SSm dvostanovanjska stavba"}' if name == "search" else f'{{"id": "ZVUP-0-{r}"}}'
    call_id = f"call_{r:03d}"
    target = rng.randint(chars[0], chars[1]) // 3
    result = corpus.sl_ordinance(rng, f"Izvleček iz baze predpisov, zadetek {r + 1} (fiktivni)", target)
    return [
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}]},
        {"role": "tool", "tool_call_id": call_id, "content": result},
    ]


def build_requests(scenario_id: str, out_dir: Path, payload: str = "text", model: Optional[str] = None,
                   extra_body: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Build the ordered request steps of a /v1 scenario.

    Args:
        scenario_id: ``V1-01`` .. ``V1-05``.
        out_dir: Directory passed to ``generate`` (files must exist).
        payload: ``text`` or ``file_parts``.
        model: Optional ``model`` field for every body.
        extra_body: Extra top-level keys merged into every body.

    Returns:
        Steps ``{"conversation", "turn", "step", "stateless", "body"}`` where
        ``step`` is ``user``, ``tool_round`` (a continuation that replays the
        original user message, file parts included) or ``forced_final``.
    """
    scenario = gen.get_scenario(scenario_id)
    client = scenario.get("client") or {}
    sdir = Path(out_dir) / scenario_id
    manifest = gen.load_manifest(out_dir, scenario_id)
    by_key = {e["key"]: e for e in manifest["files"]}
    rng = random.Random(gen.BASE_SEED)
    stateful = client.get("stateful", True)
    steps: List[Dict[str, Any]] = []
    for conv in gen.conversations(scenario):
        sent: List[str] = []
        for turn in conv:
            new = [k for k in turn.attach if k not in sent]
            keys = (sent + new) if turn.extra.get("resend_all") else list(turn.attach)
            if turn.extra.get("resend_twice"):
                keys = keys + keys
            sent += [k for k in new if k not in sent]
            entries = [by_key[k] for k in keys]
            prompt = turn.prompt
            extract_key = turn.extra.get("extract")
            if extract_key:
                (ekey,) = gen.resolve_selector(extract_key, gen.file_specs(scenario))
                extract = _entry_text(sdir, by_key[ekey])
                if payload == "text":
                    contract = "\n\n".join(_entry_text(sdir, e) or "" for e in entries)
                    content: Any = f"{prompt}\n\nContract:\n{contract}\n\nExtract:\n{extract}"
                else:
                    content = [{"type": "text", "text": f"{prompt}\n\nExtract:\n{extract}"},
                               *[file_part(sdir, e) for e in entries]]
            else:
                content = _user_content(sdir, entries, prompt, payload)
            messages: List[Dict[str, Any]] = []
            if client.get("system", True):
                messages.append({"role": "system", "content": SYSTEM_PROMPT})
            messages.append({"role": "user", "content": content})
            forced = bool(turn.extra.get("forced_final"))
            tools = [] if forced else client_tools(client.get("tools", []))
            body: Dict[str, Any] = {"messages": list(messages), "stream": bool(client.get("stream", True))}
            if tools:
                body["tools"] = tools
            if model:
                body["model"] = model
            body.update(extra_body or {})
            meta = {"conversation": turn.conversation, "turn": turn.index, "stateless": not stateful}
            steps.append({**meta, "step": "forced_final" if forced else "user", "body": body})
            if forced:
                continue
            for r in range(int(client.get("tool_rounds", 0))):
                messages += _tool_round(rng, r, client.get("tool_result_chars", [2000, 8000]))
                steps.append({**meta, "step": "tool_round", "body": {**body, "messages": list(messages)}})
    return steps
