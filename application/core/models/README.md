# Model catalogs

Each `*.yaml` file in this directory declares one provider's model
catalog. The registry loads every YAML at boot and joins it to the
matching provider plugin under `application/llm/providers/`.

To add or edit models, you almost always only touch a YAML here — no
Python code required.

## Add a model to an existing provider

Open the provider's YAML (e.g. `anthropic.yaml`) and append two lines
under `models:`:

```yaml
models:
  - id: claude-3-7-sonnet
    display_name: Claude 3.7 Sonnet
```

Capabilities default to the provider's `defaults:` block. Override
per-model only when needed:

```yaml
  - id: claude-3-7-sonnet
    display_name: Claude 3.7 Sonnet
    context_window: 500000
```

Restart the app. The new model appears in `/api/models`.

> The model `id` is what gets stored in agent / workflow records. Once
> users start picking the model, **don't rename it** — agent and
> workflow rows reference it as a free-form string and silently fall
> back to the system default if the id disappears.

## Add an OpenAI-compatible provider (zero Python)

Drop a YAML in this directory (or in your `MODELS_CONFIG_DIR`) that uses
the `openai_compatible` plugin. Set the env var named in `api_key_env`
and you're done — no Python, no settings.py edit, no LLMCreator change:

```yaml
# mistral.yaml
provider: openai_compatible
display_provider: mistral             # shown in /api/models response
api_key_env: MISTRAL_API_KEY          # env var the plugin reads at boot
base_url: https://api.mistral.ai/v1
defaults:
  supports_tools: true
  context_window: 128000
models:
  - id: mistral-large-latest
    display_name: Mistral Large
  - id: mistral-small-latest
    display_name: Mistral Small
```

`MISTRAL_API_KEY=sk-... ; restart` — Mistral models appear in
`/api/models` with `provider: "mistral"`. They route through the OpenAI
wire format (it's `OpenAILLM` under the hood) but with Mistral's
endpoint and key.

Multiple `openai_compatible` YAMLs coexist: each file is one logical
endpoint with its own `api_key_env` and `base_url`. Drop in
`together.yaml`, `fireworks.yaml`, etc. side by side. If an env var
isn't set, that catalog is silently skipped at boot (logged at INFO) —
no error.

Working example: `examples/mistral.yaml.example`. Files inside
`examples/` aren't loaded by the registry; the glob only picks up
`*.yaml` at the top level.

## Add a provider with its own SDK

For a provider that doesn't speak OpenAI's wire format, add one Python
file to `application/llm/providers/<name>.py`:

```python
from application.llm.providers.base import Provider
from application.llm.my_provider import MyLLM

class MyProvider(Provider):
    name = "my_provider"
    llm_class = MyLLM

    def get_api_key(self, settings):
        return settings.MY_PROVIDER_API_KEY
```

Register it in `application/llm/providers/__init__.py` (one line in
`ALL_PROVIDERS`), add `MY_PROVIDER_API_KEY` to `settings.py`, and create
`my_provider.yaml` here with the model catalog.

## Schema reference

```yaml
provider: <string, required>          # matches the Provider plugin's `name`

# openai_compatible only — required for that provider, ignored for others
display_provider: <string>            # label shown in /api/models response
api_key_env: <string>                 # name of the env var carrying the key
base_url: <string>                    # endpoint URL

defaults:                              # optional, applied to every model below
  supports_tools: bool                 # default false
  supports_structured_output: bool     # default false
  supports_streaming: bool             # default true
  attachments: [<alias-or-mime>, ...]  # default []
  context_window: int                  # default 128000
  input_cost_per_token: float          # default null
  output_cost_per_token: float         # default null

models:                                # required
  - id: <string, required>             # the value persisted in agent records
    display_name: <string>             # default: id
    description: <string>              # default: ""
    enabled: bool                      # default true; false hides from /api/models
    base_url: <string>                 # optional custom endpoint for this model
    # All `defaults:` fields above can be overridden here per-model.
```

### Attachment aliases

The `attachments:` list can mix human-readable aliases with raw MIME
types. Aliases are defined in `_defaults.yaml`:

| Alias | Expands to |
|---|---|
| `image` | `image/png`, `image/jpeg`, `image/jpg`, `image/webp`, `image/gif` |
| `pdf` | `application/pdf` |
| `audio` | `audio/mpeg`, `audio/wav`, `audio/ogg` |

Use raw MIME types when you need surgical control:

```yaml
attachments: [image/png, image/webp]   # only these two
```

## Operator-supplied YAMLs (`MODELS_CONFIG_DIR`)

Set the `MODELS_CONFIG_DIR` env var (or `.env` entry) to a directory
path. Every `*.yaml` in that directory is loaded **after** the built-in
catalog under `application/core/models/`. Operators use this to:

- Add new `openai_compatible` providers (Mistral, Together, Fireworks,
  Ollama, ...) without forking the repo.
- Extend an existing provider's catalog with extra models — append
  models under `provider: anthropic` and they show up alongside the
  built-ins.
- Override a built-in model's capabilities — declare the same `id`
  with different fields (e.g. a higher `context_window`). Later wins;
  the override is logged as a `WARNING` so you can audit it.

Things you cannot do via `MODELS_CONFIG_DIR`:

- Add a brand-new non-OpenAI provider — that needs a Python plugin
  under `application/llm/providers/` (see "Add a provider with its own
  SDK" above). Operator YAMLs may only target a `provider:` value that
  already has a registered plugin.

### Example: Docker

Mount your model YAMLs into the container and point the env var at the
mount path:

```yaml
# docker-compose.yml
services:
  app:
    image: arc53/docsgpt
    environment:
      MODELS_CONFIG_DIR: /etc/docsgpt/models
      MISTRAL_API_KEY: ${MISTRAL_API_KEY}
    volumes:
      - ./my-models:/etc/docsgpt/models:ro
```

Then `./my-models/mistral.yaml` (the file from
`examples/mistral.yaml.example`) gets picked up at boot.

### Example: Kubernetes

Mount a `ConfigMap` containing your YAMLs at a known path and set
`MODELS_CONFIG_DIR` on the deployment. The same `examples/mistral.yaml.example`
becomes a key in the ConfigMap.

### Misconfiguration

If `MODELS_CONFIG_DIR` is set but the path doesn't exist (or isn't a
directory), the app logs a `WARNING` at boot and continues with just
the built-in catalog. The app does *not* fail to start — operators can
ship config drift without taking down the service — but the warning is
loud enough to surface in any reasonable log aggregator.

## Validation

YAMLs are parsed with Pydantic at boot. The app fails to start with a
clear error message if:

- a top-level key is unknown
- a model is missing `id`
- an attachment alias isn't defined
- the `provider:` value isn't registered as a plugin

This is intentional — silent fallbacks would mean users don't notice
their model picks broke until they hit the API.

## Reserved fields (not yet implemented)

- `aliases:` on a model — old IDs that resolve to this model. Reserved
  for future renames; the schema accepts the field but it is not yet
  acted on.
