# ✦ Nova — Local AI Agent

**Nova is an experimental, local-first AI agent powered by [Ollama](https://ollama.com/).** It can plan multi-step tasks, use registered tools, inspect real outputs, re-plan after failures, and verify whether a task actually succeeded.

Nova is a Python agent around a locally served language model—not a newly trained foundation model. The model generates responses and proposes actions; Nova's Python code manages tool registration, permissions, execution, memory, and verification.

<p align="center">
  <strong>Local model · Real tools · Evidence-based execution · User-controlled memory</strong>
</p>

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ollama](https://img.shields.io/badge/Model%20runtime-Ollama-black)](https://ollama.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://github.com/sepehrtaji-dev/Nova-agent/actions/workflows/agent-tests.yml/badge.svg)](https://github.com/sepehrtaji-dev/Nova-agent/actions/workflows/agent-tests.yml)

> **Project status:** active development / experimental. Features and safety boundaries are evolving. Review the code and run Nova in an environment appropriate for an agent that can execute commands and modify files.

## Contents

- [Highlights](#highlights)
- [How it works](#how-it-works)
- [Available tools](#available-tools)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Running Nova](#running-nova)
- [Commands and permissions](#commands-and-permissions)
- [Memory and privacy](#memory-and-privacy)
- [Docker](#docker)
- [Development and tests](#development-and-tests)
- [Project layout](#project-layout)
- [Security notes and limitations](#security-notes-and-limitations)
- [Roadmap](#roadmap)
- [License](#license)

## Highlights

- **Local inference:** sends prompts to an Ollama model running locally or on a network endpoint you configure. Nova does not require a hosted LLM API.
- **Model-driven planning:** turns a request into steps using available tool descriptions and evidence from the current project, rather than assuming a particular language or framework.
- **Tool execution:** calls registered tools and uses their actual output as evidence.
- **Adaptive re-planning:** can reconsider pending work after a tool result or failure; verified completed work is preserved.
- **Verification and reflection:** distinguishes a model's claim from an operation confirmed by the verifier. Unverified work should not be reported as completed.
- **Interactive terminal UIs:** Textual full-screen interface, prompt_toolkit alternative, and a Rich interface.
- **Workspace-aware file and terminal tools:** project operations are scoped to the configured workspace by default.
- **Web and Git capabilities:** public web search/fetch, supported local Git operations, and read-only GitHub inspection.
- **Local memory:** long-term user facts plus knowledge and episodic memory components, with commands to inspect and remove long-term entries.
- **Capability controls:** toggle web, Git/GitHub, and PC/file/terminal/desktop access from supported terminal interfaces.
- **Optional integrations:** desktop automation, OCR, a separate PySide6 GUI, and local image generation when their extra dependencies and models are available.

## How it works

At a high level:

1. **Understand:** Nova receives the user's request and relevant conversation/memory context.
2. **Plan:** the model proposes steps based on the available tools and observed project evidence.
3. **Act:** Nova validates the proposed tool call and executes it through the registry and permission checks.
4. **Observe:** the agent receives the real tool result, including failures where applicable.
5. **Verify:** a verifier evaluates the result; a model response alone is not proof that an operation happened.
6. **Adapt:** the planner can reorder or add pending diagnostic/repair steps when the evidence calls for it.
7. **Respond:** Nova reports what the observed results support and identifies work that remains uncertain.

The model is not trusted to grant itself permissions, fabricate tool outcomes, or override execution checks. Content read from files, webpages, repositories, or terminal output is treated as untrusted context rather than higher-priority instructions.

## Available tools

Tools are loaded through a registry. Optional tools may be unavailable when their dependencies or runtime requirements are missing.

| Capability | What it supports | Notes |
|---|---|---|
| Filesystem | List, find, read, write, edit, delete files, and create directories | Workspace paths are checked; absolute system paths have additional restrictions |
| Terminal | Run supported commands in Nova's allowed workspace | Command validation and result verification apply; this is not a general-purpose secure sandbox |
| Web | Search public information and fetch readable text from public HTTP/HTTPS pages | Requires network access |
| Git | Supported Git operations on local repositories | Repository/workspace restrictions apply |
| GitHub | Inspect repository information, code/search results, issues, pull requests, workflows, and releases | Read-only integration; uses the local GitHub CLI where configured |
| Desktop | Supported GUI and desktop actions | Optional packages and an interactive desktop session may be required |
| Image generation | Use a configured local image-generation model | Optional dependencies and model files are required; not enabled by installing core dependencies alone |

The actual registry shown by Nova at runtime is the source of truth for which tools loaded successfully.

## Requirements

- Python **3.11 or newer** (the CI workflow currently tests Python 3.11).
- [Ollama](https://ollama.com/download) installed and running.
- An Ollama-compatible model downloaded locally. Nova defaults to `qwen2.5:3b`; you can choose another installed model.
- Windows, Linux, or macOS for the core terminal agent. Optional desktop features have additional platform-specific requirements.

The model is separate from Nova's source code. Downloading the Python dependencies does not download an LLM.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/sepehrtaji-dev/Nova-agent.git
cd Nova-agent
```

### 2. Create and activate a virtual environment

**Windows PowerShell:**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

**Linux / macOS:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

If Python 3.11 is not installed, install a supported Python version first and substitute its executable in the commands above.

### 3. Install the core dependencies

```bash
python -m pip install -r requirements.txt
```

This installs the dependencies for the terminal agent and its supported interfaces.

### 4. Start Ollama and download a model

Install Ollama from [ollama.com](https://ollama.com/download), then open a terminal and run:

```bash
ollama pull qwen2.5:3b
ollama list
```

Ollama normally starts its local service automatically. If it is not running, start it using the method for your operating system.

### 5. Launch Nova

```bash
python main.py
```

The default entry point launches the Textual terminal UI. See [Running Nova](#running-nova) for alternative interfaces.

## Configuration

Nova reads the following environment variables where noted in the code:

| Variable | Default | Purpose |
|---|---|---|
| `NOVA_MODEL` | `qwen2.5:3b` | Name of the Ollama model to use |
| `NOVA_NUM_CTX` | `8192` | Requested context budget; invalid values fall back to the code default |
| `NOVA_NUM_PREDICT` | `2048` | Requested output-token budget; invalid values fall back to the code default |
| `OLLAMA_HOST` | Ollama client's default | Ollama server address; useful when Ollama is not at its default local endpoint |
| `NOVA_IMAGE_MODEL_PATH` | Not set | Model-path setting used by the optional image-generation tool |
| `NOVA_EPISODIC_MEMORY_PATH` | Package-local `memory/episodic.json` | Optional override for the episodic-memory JSON file path |

Example for a model already installed in Ollama:

**Windows PowerShell**
```powershell
$env:NOVA_MODEL = "qwen2.5:3b"
python main.py
```

**Linux / macOS**
```bash
export NOVA_MODEL="qwen2.5:3b"
python main.py
```

Use a model that is actually installed in your Ollama instance. Hardware requirements depend on the chosen model, quantization, context size, and the amount of memory available.

## Running Nova

Choose one of the supported terminal interfaces:

```bash
# Default full-screen Textual UI
python main.py

# prompt_toolkit CLI
python main.py --prompt-toolkit

# Legacy Rich interface
python main.py --rich
```

The interfaces share Nova's core agent logic. The Textual interface runs agent work in a worker so model calls do not block its UI event loop.

## Commands and permissions

The supported commands can differ slightly by interface and version. Use `/help` in the running UI to see the commands available in that interface.

| Command | Purpose |
|---|---|
| `/help` | Show the command list |
| `/status` | Show a quick local runtime summary |
| `/self` | Inspect runtime components and available model metadata |
| `/model` | Query Ollama for model metadata |
| `/tools` | Show registered tools and capability states |
| `/doctor` | Run local diagnostics |
| `/permissions` | Show current capability toggles |
| `/web` | Toggle web access |
| `/git` | Toggle Git and GitHub access |
| `/pc` | Toggle PC, filesystem, terminal, and desktop capability |
| `/memory` | Inspect saved long-term memory entries |
| `/forget <category> <key>` | Remove a matching long-term memory entry |
| `/clear` | Clear the current view or conversation, depending on the interface |
| `/reset` | Start a fresh agent session |
| `/exit` | Exit Nova |

Example:

```text
/forget profile gpu
```

Capability toggles are not a substitute for operating-system isolation. Keep permissions limited to what you need, especially when asking Nova to operate on unfamiliar files or repositories.

## Memory and privacy

Nova has multiple memory components for different purposes:

- **Long-term memory:** selected user facts stored in `memory/long_term.json`. Use `/memory` to inspect entries and `/forget <category> <key>` to remove one.
- **Knowledge memory:** persisted knowledge data managed by the knowledge-memory component.
- **Episodic memory:** bounded summaries of tool outcomes, rather than a raw transcript of every tool input/output.
- **Short-term conversation memory:** recent context maintained during the current session.

The long-term memory extractor is designed to be conservative and reject credential-like values. That does not make Nova a secret manager, and it is not a guarantee that every sensitive value can be detected. **Do not provide passwords, API keys, access tokens, private keys, or other secrets for Nova to remember.**

Runtime memory files are local application data and should not be committed. The repository's `.gitignore` excludes memory JSON files and the default projects workspace. Review your local configuration and any files you intentionally share before publishing logs or project artifacts.

Nova uses a local Ollama model by default, but web search/fetch and any other enabled network-facing tools can contact external services. “Local-first” does not mean that every feature is offline.

## Docker

The Docker setup runs Nova and Ollama as separate containers. The Ollama model is stored in a named Docker volume, project files are mounted from your host, and Nova runs as a non-root user inside its container.

**Prerequisites:** Docker Engine/Desktop with the Compose plugin. The example below uses CPU execution for Ollama by default; GPU passthrough depends on your OS and Docker/NVIDIA setup and is not configured automatically.

### 1. Build the Nova image

```bash
docker compose build
```

### 2. Start Ollama

```bash
docker compose up -d ollama
```

### 3. Download the model into the Ollama container

```bash
docker compose exec ollama ollama pull qwen2.5:3b
```

To use a different model, set `NOVA_MODEL` in your environment before starting Nova and pull that model into the Ollama container first.

### 4. Run Nova interactively

```bash
docker compose run --rm nova
```

The Compose setup mounts your host's `projects/` directory into Nova's workspace and uses a named volume for runtime memory data. Files created in the project workspace are therefore available on the host. To stop the Ollama service:

```bash
docker compose down
```

The named model and memory volumes are preserved by default. To remove those volumes too, use `docker compose down --volumes`; this deletes their persisted contents.

The container is isolated from your host desktop and host filesystem except for explicitly mounted directories, but Nova can still execute commands and modify files within its container/workspace. Do not mount sensitive host directories or the Docker socket into the container.

## Development and tests

Install the core requirements, then run the test suite from the repository root:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Compile the main Python packages:

```bash
python -m compileall -q agent tools memory model ui main.py App.py
```

The GitHub Actions workflow runs these checks on pushes and pull requests targeting `main`. Unit tests use controlled test doubles for many tool/model paths; passing tests does not mean every integration has been exercised against a live Ollama server or real desktop.

Optional integrations can be installed separately:

```bash
python -m pip install -r requirements-optional.txt
```

These extras include desktop automation, OCR, PySide6, and local image-generation dependencies. Some features need additional system software or model files. For example, `pytesseract` needs the Tesseract OCR application installed separately; installing the Python package alone is not enough.

## Project layout

```text
Nova-agent/
├── agent/                  # Core orchestration, planning, routing, verification
├── memory/                 # Memory implementations and persistence helpers
├── model/                  # Ollama model adapter and prompts
├── tools/                  # Tool registry and filesystem/web/Git/desktop tools
├── ui/                     # Textual and prompt_toolkit terminal interfaces
├── utils/                  # Shared utilities
├── tests/                  # Unit and regression tests
├── sandbox/                # Sandbox-related components
├── projects/               # Runtime workspace (ignored by Git)
├── App.py                  # Optional desktop GUI entry point
├── main.py                 # Rich interface and CLI launch dispatch
├── requirements.txt        # Core Python dependencies
├── requirements-optional.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .github/workflows/      # CI checks
├── LICENSE
└── README.md
```

## Security notes and limitations

Nova is an experimental agent with tools that can affect files and execute programs. Follow these precautions:

- Run it as a normal, non-administrator user.
- Start with only the capabilities you need; turn off PC, Git, or web access when not needed.
- Review proposed plans and tool results, particularly for destructive or irreversible actions.
- Treat files, repository instructions, webpages, and command output as untrusted data.
- Use a separate test workspace for unfamiliar projects.
- Never put secrets in prompts or long-term memory.
- Keep Ollama and other local services updated and avoid exposing their ports publicly.
- Remember that Docker limits access to the host only to the extent that you configure its mounts, networking, privileges, and runtime.

Nova's verification and safety checks reduce certain failure modes; they do not guarantee correctness, prevent every unsafe action, or replace human review. The project is not intended for unattended operation on important systems.

## Roadmap

Development is incremental. Areas of ongoing work include:

- More reliable model-driven coding and repair loops
- Better evidence-based tool selection and recovery
- More general memory retrieval without task-specific keyword rules
- Expanded regression coverage for real-world failures
- Improved configuration and deployment ergonomics
- Clearer runtime observability and permission boundaries

This list describes development direction, not a promise that every item is already implemented.

## License

Nova-agent source code is distributed under the [MIT License](LICENSE). Third-party packages, Ollama models, and any optional image-generation model files have their own licenses and terms; those are not replaced by Nova's repository license.

---

Made by [Sepehr Taji](https://github.com/sepehrtaji-dev).
