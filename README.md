# ✦ Nova — Local-First AI Agent

Nova is an experimental, tool-using AI agent written in Python. It connects a language model to a real tool system so it can understand a request, plan work, call tools, inspect the results, revise its plan, and verify whether an operation actually succeeded.

Nova is an **agent application**, not a newly trained foundation model. You choose the model that powers it. Nova provides the orchestration, tools, permissions, memory, interfaces, and verification around that model.

<p align="center">
  <strong>Choose your model · Give it tools · Observe its work · Verify the result</strong>
</p>

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ollama](https://img.shields.io/badge/Local%20models-Ollama-black)](https://ollama.com/)
[![Remote API](https://img.shields.io/badge/Remote%20models-OpenAI--compatible-6B5B95)](#model-providers)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/sepehrtaji-dev/Nova-agent/actions/workflows/agent-tests.yml/badge.svg)](https://github.com/sepehrtaji-dev/Nova-agent/actions/workflows/agent-tests.yml)

> **Status: active development / experimental.** Features and safety boundaries can change. Nova can execute programs and modify files when those capabilities are enabled. Read the security notes before using it on important data.

## Contents

- [What Nova can do](#what-nova-can-do)
- [Architecture](#architecture)
- [Model providers](#model-providers)
- [Task execution flow](#task-execution-flow)
- [Tools and permissions](#tools-and-permissions)
- [Memory system](#memory-system)
- [Interfaces](#interfaces)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Commands](#commands)
- [Project structure](#project-structure)
- [Development and tests](#development-and-tests)
- [Repository snapshot](#repository-snapshot)
- [Docker](#docker)
- [Security and privacy](#security-and-privacy)
- [Roadmap](#roadmap)
- [License](#license)

## What Nova can do

Nova's actual capabilities depend on the tools that load, enabled permissions, optional packages, and the configured model.

- **Plan tasks:** turn natural-language requests into multi-step plans.
- **Use tools:** work with files, run supported programs, search the web, and use Git.
- **Inspect before acting:** discover files and read real content instead of assuming what exists.
- **Re-plan:** use tool results and errors to revise the remaining steps.
- **Verify actions:** distinguish confirmed, failed, and unverifiable operations.
- **Use memory:** maintain conversation context, long-term facts, knowledge records, and summaries of previous tool outcomes.
- **Inspect itself:** report runtime components, model metadata when available, tools, permissions, and diagnostics.
- **Switch model backends:** run a local Ollama model or connect to an OpenAI-compatible API.
- **Use different interfaces:** Textual terminal UI, prompt_toolkit CLI, legacy Rich UI, and an optional PySide6 desktop GUI.

Nova does not guarantee that every model will plan or use tools correctly. Smaller models may need more retries or produce invalid tool arguments. Review important operations.

## Architecture

Nova separates the language model from the Python application that controls tools and state.

| Layer | Responsibility |
|---|---|
| User interface | Accept requests and display responses, activity, and runtime status |
| NovaCore | Coordinate tasks, memory, tools, permissions, and execution state |
| Model provider | Generate responses through Ollama or an OpenAI-compatible API |
| Planner | Propose and update task steps |
| Tool router | Interpret model-selected tool calls and route them |
| Tool registry | Store handlers, descriptions, schemas, capabilities, and verifier metadata |
| Permission layer | Control which capability groups are enabled |
| Verifier | Check tool outcomes against observable state |
| Memory services | Maintain conversation and persisted memory |
| Diagnostics / introspection | Report observable runtime and model information |

The model proposes what to do. It does **not** grant itself permissions or manufacture successful tool results. Nova's Python code validates and executes tool calls, then provides the actual result back to the agent.

### Core components

- **NovaCore — agent/core.py:** creates the configured model backend, memory services, tool registry, planner, router, verifier, diagnostics, and execution state. It coordinates each task.
- **Planner — agent/planner.py:** asks the model to create and update a structured plan.
- **ToolRouter — agent/router.py:** extracts structured tool requests from model output and maps them to registered tools.
- **ToolRegistry — tools/registry.py:** stores tool callables and metadata, including capability groups, input schemas, optional input preparation, and verifier methods.
- **Verifier — agent/verifier.py:** checks whether operations succeeded using filesystem state, command results, or tool-specific checks where implemented.
- **SelfReflection — agent/self_reflection.py:** compares plan state with verifier evidence. It is an evidence audit, not a claim that the model's private reasoning is correct.
- **SelfKnowledge and introspection:** report Nova's components and observed runtime configuration. Unknown metadata should remain unknown rather than guessed.

Tool definitions are data-driven. The manifest at **config/tools.json** is read by **tools/__init__.py**, which imports configured handler classes and registers enabled tools. The live registry is the source of truth for tools available in a particular run.

### Task execution flow

1. **Receive:** Nova receives the request and prepares relevant conversation and memory context.
2. **Plan:** the configured model proposes steps using the currently available tools.
3. **Validate:** Nova checks the requested tool against the registry and its capability permission.
4. **Execute:** the registered Python handler runs and returns its real result.
5. **Verify:** the verifier checks the result. A model's success claim is not proof that a file was written or a command succeeded.
6. **Adapt:** the planner can revise remaining work using new evidence or a failure.
7. **Reflect and respond:** Nova reports what is confirmed, failed, or still uncertain.

A simple conversation may not need planning or tools.

## Model providers

Both providers implement the same small generation interface, allowing the planner, router, and memory extractor to use either backend.

### Local: Ollama

The local provider uses the Ollama Python client and an Ollama server.

- Configure the model with **NOVA_MODEL**.
- If no model name is configured, Nova attempts to discover an installed Ollama model.
- Context and output budgets are configurable.
- Model metadata can be queried from Ollama when available.
- When Ollama runs on the same computer, inference can remain on that computer.

Install Ollama: https://ollama.com/download

Example:

\`\`\`bash
ollama pull qwen2.5:3b
ollama list
\`\`\`

This is only an example model. You can use another model supported by your Ollama installation.

### Remote: OpenAI-compatible API

The remote provider uses the standard chat-completions HTTP protocol. It is intended to work with services exposing an OpenAI-compatible endpoint, such as OpenAI, OpenRouter, Groq, Together, Fireworks, DeepSeek, or compatible self-hosted gateways such as vLLM and LM Studio.

Configure these environment variables:

- **NOVA_PROVIDER=remote**
- **NOVA_API_BASE_URL**
- **NOVA_API_MODEL**
- **NOVA_API_KEY**

The remote client uses Python's standard library rather than requiring a vendor SDK. It supports JSON-mode requests where accepted by the provider, timeouts, retries for transient failures, rate-limit handling, and API-key redaction in error text.

**Privacy difference:** with a remote provider, prompts, tool results, and file contents included in a request are sent to that provider. Nova's tools may still execute locally, but the reasoning model runs remotely. Review the provider's data policy before enabling remote mode.

### Provider selection

| NOVA_PROVIDER | Behaviour |
|---|---|
| local | Use Ollama (default) |
| remote | Require a configured remote API; fail clearly if configuration is incomplete |
| auto | Use remote only when a remote model and API key are configured; otherwise use Ollama |

Nova intentionally does not silently switch from a selected remote model to a local model after a provider failure. Silent fallback could hide which model is answering and where prompts are being processed.

### Model settings in the desktop GUI

The optional PySide6 desktop application includes settings for selecting a local model or entering a remote API base URL, model name, and key. These settings are applied to the same NOVA environment configuration used by the provider layer.

The current implementation stores settings in the Nova settings JSON file, including the API key, and attempts to restrict file permissions on supported systems. This is best-effort protection, not an operating-system credential vault. Keep the settings file private and never commit it.

## Tools and permissions

The default manifest currently defines **8 tools**:

| Tool | Capability | What it does |
|---|---|---|
| web_search | web | Search the public web and return result titles, URLs, and snippets |
| list_files | pc | List entries in a workspace directory |
| read_file | pc | Read text files |
| write_file | pc | Create or overwrite files with complete content |
| terminal | pc | Run one supported non-interactive program with arguments |
| git | git | Perform supported local Git operations |
| github | git | Read-only GitHub inspection through the authenticated gh CLI |
| desktop | pc | Optional GUI and desktop actions |

A tool being present in the manifest does not guarantee that it loads successfully. Optional dependencies, platform support, authentication, and runtime conditions can affect availability. Check **/tools** or **/self** in a running session.

### Capability groups

- **Web:** public web search.
- **Git:** local Git and read-only GitHub operations.
- **PC:** filesystem, terminal, and desktop operations.

The default manifest enables all three groups. You can toggle them during a terminal session with **/web**, **/git**, and **/pc**. These switches control Nova's tool access; they are not a replacement for operating-system security or process isolation.

### Filesystem and terminal

Filesystem tools support workspace locations such as:

- **projects:** Nova's configured project workspace; the default for most file operations.
- **desktop:** the user's Desktop directory.
- **system:** absolute paths, subject to protected-path checks and operation restrictions.

Use each tool's live input schema for exact path rules. The terminal tool is intentionally narrower than a general shell: it accepts a program and arguments, and does not provide arbitrary shell pipelines, redirects, command chaining, or inline interpreter code. Use the dedicated file tools for file operations.

### GitHub integration

The **github** tool uses the locally authenticated GitHub CLI and is read-only. It can inspect repositories, issues, pull requests, workflow runs, releases, and code search. It cannot create, modify, merge, or delete GitHub resources. Local Git operations are provided separately by the **git** tool.

## Memory system

Nova uses separate memory components for different kinds of context.

| Component | Purpose |
|---|---|
| Short-term memory | Recent conversation context for the current session |
| Long-term memory | Selected user facts stored for later sessions |
| Knowledge memory | Topic/fact records with source, confidence, verification time, and optional expiry |
| Episodic memory | Bounded summaries of previous tool outcomes |
| Memory extractor | Selects candidate long-term facts from conversation using the configured model |

Episodic memory stores concise task/tool outcome summaries rather than raw tool inputs and full raw tool outputs. Records are bounded and can have statuses such as **confirmed**, **failed**, and **unverifiable**. Secret-like strings are filtered before episodic summaries are saved, but this is a safeguard, not a guarantee.

Memory is local application data. Do not ask Nova to store passwords, API keys, access tokens, private keys, or other secrets. Do not commit runtime memory files.

## Interfaces

Nova has several front ends over the same agent core.

| Interface | Command | Description |
|---|---|---|
| Textual terminal UI | python main.py | Default full-screen terminal application |
| prompt_toolkit CLI | python main.py --prompt-toolkit | Alternative interactive terminal interface |
| Rich interface | python main.py --rich | Earlier Rich-based terminal interface |
| PySide6 desktop GUI | python App.py | Optional desktop application; requires optional GUI dependencies |

The Textual and prompt_toolkit interfaces use the same core orchestration. The desktop GUI is an optional front end and requires PySide6.

## Requirements

- Python **3.11 or newer**.
- **Ollama** and at least one downloaded model for local inference, or credentials for a compatible remote API.
- **Git** installed for local Git features.
- **gh CLI** authenticated with **gh auth login** for read-only GitHub integration.
- Windows, Linux, or macOS for the core terminal agent. Individual optional tools may have narrower platform requirements.

Core dependencies in **requirements.txt**:

- ollama
- rich
- textual
- prompt_toolkit

Optional dependencies in **requirements-optional.txt** include PySide6, desktop automation, OCR, image processing, and local image-generation packages. Some extras require separate system software or model files. For example, pytesseract also needs the Tesseract OCR application.

## Quick start

### 1. Clone the repository

\`\`\`bash
git clone https://github.com/sepehrtaji-dev/Nova-agent.git
cd Nova-agent
\`\`\`

### 2. Create a virtual environment

**Windows PowerShell**

\`\`\`powershell
py -3.11 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
\`\`\`

**Linux / macOS**

\`\`\`bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
\`\`\`

### 3. Install dependencies

\`\`\`bash
python -m pip install -r requirements.txt
\`\`\`

For the optional desktop GUI and integrations:

\`\`\`bash
python -m pip install -r requirements-optional.txt
\`\`\`

Install optional extras only if you need them. Some packages, especially local image-generation stacks, can be large and may need compatible hardware and separately downloaded model files.

### 4. Configure a model

**Local Ollama**

Install and start Ollama, then download a model:

\`\`\`bash
ollama pull qwen2.5:3b
ollama list
\`\`\`

**Remote API — PowerShell example**

\`\`\`powershell
$env:NOVA_PROVIDER = "remote"
$env:NOVA_API_BASE_URL = "https://api.openai.com/v1"
$env:NOVA_API_MODEL = "your-model-name"
$env:NOVA_API_KEY = "your-api-key"
\`\`\`

Use the base URL and model name supplied by your provider. Never put a real API key in a committed file, issue, screenshot, or log.

### 5. Launch Nova

\`\`\`bash
python main.py
\`\`\`

The default launch opens the Textual terminal interface. See [Interfaces](#interfaces) for alternatives.

## Configuration

| Variable | Default / behaviour | Purpose |
|---|---|---|
| NOVA_PROVIDER | local | Select local, remote, or auto |
| NOVA_MODEL | Auto-detect installed Ollama model if empty | Local model name |
| NOVA_API_BASE_URL | https://api.openai.com/v1 | OpenAI-compatible API base URL |
| NOVA_API_MODEL | Required for remote mode | Remote model identifier |
| NOVA_API_KEY | Required for remote mode | Remote API credential |
| NOVA_API_TIMEOUT | 120 seconds | Remote request timeout |
| NOVA_NUM_CTX | 8192 | Requested local Ollama context budget |
| NOVA_NUM_PREDICT | 1536 in current Ollama adapter | Requested local output-token budget |
| NOVA_MAX_STEPS | 12 | Maximum task execution steps |
| OLLAMA_HOST | Ollama client default | Ollama server address |
| NOVA_HOME | ~/.nova | Base directory for desktop settings |
| NOVA_SETTINGS_FILE | ~/.nova/settings.json | Override desktop settings file |
| NOVA_TOOL_MANIFEST | config/tools.json | Override tool manifest |
| NOVA_EPISODIC_MEMORY_PATH | memory/episodic.json | Override episodic-memory storage |
| NOVA_IMAGE_MODEL_PATH | Not set | Optional local image model path |

Docker Compose supplies its own default model (qwen2.5:3b) and context/output settings. Environment variables can override those values.

### Choose a different local model

**Windows PowerShell**

\`\`\`powershell
$env:NOVA_PROVIDER = "local"
$env:NOVA_MODEL = "your-installed-ollama-model"
python main.py
\`\`\`

**Linux / macOS**

\`\`\`bash
export NOVA_PROVIDER=local
export NOVA_MODEL=your-installed-ollama-model
python main.py
\`\`\`

Use a model actually installed in your Ollama instance. Performance and memory requirements depend on model size, quantization, context length, and available hardware.

## Commands

Use **/help** inside the running terminal interface to see the commands supported by that UI version.

| Command | Purpose |
|---|---|
| /help | Show available commands |
| /status | Show runtime status |
| /self | Inspect Nova's runtime profile and components |
| /model | Query model metadata when supported by the active backend |
| /tools | List registered tools and capability states |
| /doctor | Run runtime diagnostics |
| /permissions | Show capability permissions |
| /web | Toggle web access |
| /git | Toggle Git and GitHub access |
| /pc | Toggle filesystem, terminal, and desktop access |
| /memory | Inspect long-term memory entries |
| /forget category key | Remove a matching long-term memory entry |
| /clear | Clear the current terminal view |
| /reset | Start a new Nova session |
| /exit | Exit Nova |

Some commands vary between interfaces and may evolve. Runtime **/help** output is authoritative.

## Project structure

The repository is organized by responsibility instead of placing all agent logic in one file.

\`\`\`text
Nova-agent/
├── agent/                       # Agent orchestration and decision workflow
│   ├── core.py                  # NovaCore: connects agent services
│   ├── router.py                # Parses and routes model-selected tool calls
│   ├── planner.py               # Creates and updates task plans
│   ├── verifier.py              # Verifies observable tool outcomes
│   ├── self_knowledge.py        # Nova's self-knowledge component
│   ├── self_reflection.py      # Evidence-based completion audit
│   ├── introspection.py         # Runtime and model inspection
│   ├── capability_probe.py     # Live capability/model probes
│   ├── tool_awareness.py       # Builds tool context from the registry
│   ├── diagnostics.py           # Runtime diagnostics
│   └── identity.py              # Static Nova identity
│
├── model/                       # Model provider adapters
│   ├── provider.py              # Selects the active backend
│   ├── ollama.py                # Local Ollama implementation
│   ├── remote.py                # OpenAI-compatible API implementation
│   └── ...                      # Shared prompts and model helpers
│
├── tools/                       # Executable capabilities
│   ├── __init__.py              # Loads tools from the manifest
│   ├── registry.py              # Tool registry and metadata
│   ├── filesystem.py            # File and directory operations
│   ├── terminal.py              # Restricted program execution
│   ├── web.py                   # Public web search/fetch
│   ├── git.py                   # Local Git operations
│   ├── github.py                # Read-only GitHub CLI integration
│   ├── desktop.py               # Optional desktop automation
│   └── ...                      # Tool-specific helpers
│
├── memory/                      # Memory and persistence
│   ├── manager.py               # Long-term memory manager
│   ├── extractor.py             # Candidate fact extraction
│   ├── short_term.py            # Conversation context
│   ├── knowledge.py             # Topic/fact knowledge store
│   └── episodic.py              # Bounded tool-outcome history
│
├── config/
│   ├── tools.json               # Declarative tool/capability manifest
│   ├── runtime.py               # Loads manifest settings
│   └── model_settings.py        # Desktop model settings persistence
│
├── ui/
│   ├── launcher.py              # Selects terminal interface
│   ├── textual_app.py           # Default Textual UI
│   └── prompt_cli.py            # prompt_toolkit interface
│
├── utils/                       # Shared helpers and utilities
├── tests/                       # Unit and regression tests
├── sandbox/                     # Sandbox-related code
├── projects/                    # Runtime workspace (normally Git-ignored)
├── App.py                       # Optional PySide6 desktop GUI
├── main.py                      # Terminal UI launch entry point
├── requirements.txt              # Core dependencies
├── requirements-optional.txt    # Optional integrations
├── Dockerfile                   # Container image
├── docker-compose.yml           # Nova + Ollama Compose setup
├── .github/workflows/           # GitHub Actions CI
├── LICENSE
└── README.md
\`\`\`

The diagram highlights the main modules; individual helper files and tests are omitted.

## Development and tests

Run the tests from the repository root:

\`\`\`bash
python -m unittest discover -s tests -p "test_*.py"
\`\`\`

Compile the Python sources:

\`\`\`bash
python -m compileall -q agent tools memory model ui main.py App.py
\`\`\`

Smoke-test the terminal UI imports:

\`\`\`bash
python -c "from ui.textual_app import NovaTextualApp; from ui.prompt_cli import main; print('UI imports OK')"
\`\`\`

### CI workflow

GitHub Actions currently:

1. Checks out the repository.
2. Sets up Python 3.11.
3. Compiles Python packages and entry points.
4. Installs core dependencies.
5. Smoke-tests Textual and prompt_toolkit imports.
6. Runs the unit/regression test suite.
7. Builds the Docker image if earlier steps pass.

Tests use controlled test doubles for many model and tool paths. A green test run does not mean every provider, desktop action, or real-world integration has been exercised.

## Repository snapshot

These figures are a source-repository snapshot from the review on **30 October 2026**. They exclude runtime memory, downloaded models, virtual environments, and user workspace files.

| Metric | Snapshot |
|---|---:|
| Tracked files | 86 |
| Python files | 75 |
| Test files | 26 |
| Tracked file content | ~871 KB |
| Tools in default manifest | 8 |
| Default capability groups | 3 (web, git, pc) |
| Model backends | 2 (Ollama and OpenAI-compatible API) |
| Terminal interfaces | 3 |
| Optional desktop GUI | PySide6 |

### Latest reviewed changes and CI

The latest reviewed main-branch commit at the time of this snapshot was **9518b521** — “Selfknowledge improvement” (18 October 2026). It included updates to self-knowledge, core integration, model handling, and tests, plus a large added Apptest.py file.

The last reviewed GitHub Actions run for that commit executed **273 tests: 268 passed, 1 failed, and 4 were skipped**. The failure was **test_legitimate_paths_are_not_over_blocked** in **tests/test_filesystem_security.py**: a Windows-style path (C:/projects/nova/main.py) was incorrectly treated as a protected path on the Linux CI runner.

Check the [GitHub Actions page](https://github.com/sepehrtaji-dev/Nova-agent/actions) for the current run state. CI status may have changed after this snapshot.

## Docker

Nova can run in Docker with Ollama as a separate service. You need Docker Engine or Docker Desktop with the Compose plugin.

Build the Nova image and start Ollama:

\`\`\`bash
docker compose build
docker compose up -d ollama
\`\`\`

Download a model into the Ollama container:

\`\`\`bash
docker compose exec ollama ollama pull qwen2.5:3b
\`\`\`

Run Nova:

\`\`\`bash
docker compose run --rm nova
\`\`\`

The Compose setup stores Ollama model data and Nova memory in named volumes. It mounts the host **projects/** directory into the container workspace, so files created there are available on the host.

The example uses CPU execution by default. GPU passthrough is not configured automatically and depends on the host OS, Docker, and NVIDIA setup.

Stop services:

\`\`\`bash
docker compose down
\`\`\`

Remove named volumes too (this deletes persisted model and memory data):

\`\`\`bash
docker compose down --volumes
\`\`\`

Do not mount sensitive host directories or the Docker socket into the container. Isolation depends on the mounts, privileges, networking, and runtime configuration you choose.

## Security and privacy

Nova can run programs and change files when relevant tools are enabled. Treat it as software with real access, not as a chat-only application.

- Run Nova as a normal user, not as an administrator.
- Enable only the capabilities you need.
- Use a separate test workspace for unfamiliar projects.
- Review plans and tool results before destructive or irreversible operations.
- Never put passwords, API keys, tokens, or private keys in prompts or memory.
- Keep API credentials and settings files private. The desktop settings file currently includes the configured API key; permission restriction is best-effort and is not a secure credential vault.
- A remote provider receives prompts and tool/file context sent to it. Local tools do not make remote inference private.
- Web search and other network-enabled tools contact external services.
- Keep Ollama, Git, Python, and optional dependencies updated.
- Do not expose local model-server ports publicly without understanding the consequences.

Filesystem and terminal restrictions reduce some risks but do not create a hardened security sandbox. Verification can catch certain failures, but cannot guarantee correctness or prevent every unsafe action. Do not use Nova for unattended operation on important systems.

## Roadmap

Development is ongoing. Current areas of focus include:

- Fixing cross-platform filesystem path edge cases and keeping CI reliable.
- Improving model-driven planning, tool selection, and recovery.
- Keeping self-knowledge grounded in live runtime evidence.
- Strengthening memory reliability and privacy safeguards.
- Improving provider configuration and credential handling.
- Expanding regression tests for real-world tool behaviour.
- Improving desktop and terminal user experience.

This roadmap describes areas of work, not features guaranteed to be complete.

## License

Nova-agent source code is distributed under the [MIT License](LICENSE). Third-party dependencies, Ollama models, remote model providers, and optional image-generation models have their own licences and terms. The repository's MIT license does not replace those terms.

---

Made by [Sepehr Taji](https://github.com/sepehrtaji-dev).
