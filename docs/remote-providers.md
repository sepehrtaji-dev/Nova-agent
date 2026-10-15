# Remote model providers

Nova can run on a local Ollama model or on a stronger model hosted by a remote
provider. Everything else in the agent -- the router, planner, verifier, memory,
and every tool -- is unchanged: only the reasoning backend is swapped.

When a remote provider is configured, the remote model is told it is **Nova 1.3
running inside the Nova desktop application on this user's computer**, and it is
given this machine's live environment and tool registry. Its tool calls execute
locally through Nova, so it behaves as the agent rather than as a generic hosted
chatbot.

The user is always told which model is actually answering, and that content is
leaving the machine.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `NOVA_PROVIDER` | `local`, `remote`, or `auto` | `local` |
| `NOVA_API_MODEL` | Model name to request | *(none)* |
| `NOVA_API_KEY` | Provider API key | *(none)* |
| `NOVA_API_BASE_URL` | OpenAI-compatible base URL | `https://api.openai.com/v1` |
| `NOVA_API_TIMEOUT` | Request timeout in seconds | `120` |

`remote` requires a model, a key, and a base URL. `auto` uses remote when a key
and model are set, otherwise local.

### Example: hosted provider

```bash
set NOVA_PROVIDER=remote
set NOVA_API_MODEL=gpt-4o-mini
set NOVA_API_KEY=sk-...
python main.py
```

### Example: a gateway or self-hosted server

Any endpoint speaking the OpenAI chat-completions protocol works, including
OpenRouter, Groq, Together, DeepSeek, LM Studio, and vLLM:

```bash
set NOVA_PROVIDER=remote
set NOVA_API_BASE_URL=https://openrouter.ai/api/v1
set NOVA_API_MODEL=anthropic/claude-sonnet-4
set NOVA_API_KEY=sk-or-...
```

## Behaviour worth knowing

- **No silent fallback.** If `NOVA_PROVIDER=remote` is set but the provider is
  not configured, Nova raises instead of quietly using the local model. Falling
  back would hide both the outage and the fact that prompts stopped leaving the
  machine.
- **Secrets are never echoed.** API keys and any secret-looking text in a
  provider error body are redacted before being logged or returned.
- **Retries are bounded and selective.** HTTP 408/409/429/5xx are retried (max 2
  by default); 400/401/403/404 fail immediately with a specific hint.
- **The base URL is read at construction time**, so changing
  `NOVA_API_BASE_URL` takes effect without a restart of the process.

## Privacy

With `local`, nothing leaves the machine. With `remote`, the following is sent to
the provider: your messages, the conversation history, file contents you ask
Nova to read, and tool results. Nova states this in its self-description, and
`model.provider.describe_brain()` returns a one-line summary suitable for
displaying in the UI.

Do not configure remote mode for work involving secrets or private data unless
you accept that exposure.

## Adding another provider

The adapter lives in `model/remote.py`. Providers that speak the OpenAI
chat-completions protocol need no code change -- set `NOVA_API_BASE_URL`. A
provider with a different protocol needs a new class exposing the same two
methods used across the codebase:

```python
def generate(self, prompt, system_prompt=None, json_mode=False, options=None) -> str
def c_gen(self, prompt, json_mode=False) -> str
```

`model/provider.py` is the single place that selects a backend, so a new class
only needs registering there.
