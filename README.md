# ✦ Nova — Local AI Agent

Nova is a local AI agent designed to interact with your computer through a model-driven tool system.

Instead of only generating text, Nova can plan tasks, use tools, inspect results, re-plan when necessary, work with files, execute terminal commands, and search the web.

The goal is to build a practical local agent that can gradually become more capable while keeping the architecture modular and understandable.

---

## ✦ Core Idea

Nova follows an agent loop:

```text
User
  ↓
Nova
  ↓
Planner
  ↓
Choose Tool
  ↓
Execute Tool
  ↓
Real Result
  ↓
Re-plan
  ↓
Next Tool
  ↓
Final Response
```

Nova does not simply assume that an operation succeeded.

Tool results are returned to the agent so Nova can decide what should happen next.

---

## ✦ Features

### 🧠 Local AI

Nova runs locally through Ollama.

Default local model:

```text
qwen2.5:3b
```

The runtime model is configurable with `NOVA_MODEL`. Context and generation
budgets can be tuned with `NOVA_NUM_CTX` and `NOVA_NUM_PREDICT`.

The model is used for:

- Planning
- Re-planning
- Memory extraction
- Tool decisions
- Final responses

---

### 🛠 Tool System

Nova currently exposes capabilities through a registry-driven tool system:

| Capability | Purpose |
|---|---|
| `web_search` | Search the public web |
| `web_fetch` | Fetch readable text from public HTTP(S) pages with size limits and local/private destination checks |
| `github` | Read-only GitHub repository, issue, pull-request, workflow, release, and code-search queries via `gh` |
| `terminal` | Execute terminal commands |
| `list_files` | List files and directories |
| `read_file` | Read text files |
| `write_file` | Create or overwrite files |
| `edit_file` | Modify existing files |
| `delete_file` | Delete files |
| `create_directory` | Create directories |
| `git` | Local Git and GitHub CLI workflows |
| `desktop` | Real mouse, keyboard, window, app, and screenshot control |
| `generate_image` | Generate local images |

Tools are registered with capability metadata. Nova derives the enabled tool set from the registry instead of maintaining a separate hard-coded tool list in the agent core.

---

## ✦ Web and GitHub research

`web_search` finds public results; `web_fetch` retrieves a bounded text view of a specific public webpage. Fetching accepts HTTP(S) only, validates redirect destinations, limits response size to 1 MB, and rejects localhost/private/reserved IP destinations. This is a defense-in-depth filter, not a substitute for keeping the local agent's environment secure.

`github` provides read-only queries through the locally installed GitHub CLI (`gh`). Supported actions include `repo_view`, `issue_list`, `issue_view`, `pr_list`, `pr_view`, `run_list`, `release_list`, and `code_search`. Install GitHub CLI and run `gh auth login` first. The tool deliberately does not create, edit, merge, or delete remote resources.

Example inputs:

```json
{"url": "https://example.com"}
{"action": "pr_list", "repo": "owner/repository", "state": "open", "limit": 5}
```

## ✦ Agent Workflow

A typical request can look like:

```text
User:
Create a Python calculator project, run it,
and fix any errors.
```

Nova can break the task into steps:

```text
1. Create the project
2. Write calculator.py
3. Run the program
4. Inspect the result
5. Fix errors if necessary
6. Run it again
7. Finish
```

The important part is that Nova receives the **real result** of each tool execution and verifies it before using it as evidence. For generated `.py` files, Nova also parses the code before writing and rejects syntax errors; this is a syntax check, not a proof that code is correct or safe to run.

For example:

```text
Planner
   ↓
write_file
   ↓
REAL FILE RESULT
   ↓
Planner
   ↓
terminal
   ↓
REAL TERMINAL RESULT
   ↓
Planner
   ↓
Fix / continue
```

---

# ✦ Terminal UI

Nova includes a full-screen Textual terminal interface, with Rich-rendered panels and activity output. A prompt_toolkit CLI is also available as a lightweight fallback. The interface is designed to make agent activity visible without exposing internal chain-of-thought.

The interface reports high-level agent activity such as:

```text
PLAN
WEB
TERM
READ
WRITE
MKDIR
THINK
DONE
ERROR
```

Example:

```text
┌──────────────────────────────────────────────────────────┐
│ ✦ NOVA   LOCAL AI AGENT                         QWEN 2.5│
└──────────────────────────────────────────────────────────┘

● LOCAL   ● TOOLS ENABLED   ● PRIVATE


┌─ ACTIVITY ───────────────────────────────────────────────┐
│ ● Planning                                               │
│                                                          │
│ 21:42:03  PLAN   Creating execution plan                 │
│ 21:42:04  WEB    Searching public web                    │
│ 21:42:07  WEB    Search completed                        │
│ 21:42:08  THINK  Processing tool result                  │
│ 21:42:11  TERM   Running terminal command                │
│ 21:42:12  DONE   Task completed                          │
│                                                          │
│ Events: 6   ·   Elapsed: 9.4s                            │
└──────────────────────────────────────────────────────────┘
```

The UI is designed to show **what Nova is doing**, rather than exposing private model reasoning.

### Long-term memory controls

Nova stores selected long-term user memories locally in `memory/long_term.json`. Use `/memory` to inspect saved entries and `/forget <category> <key>` to remove one entry (for example, `/forget profile gpu`). These commands are available in both terminal interfaces. The memory extractor also rejects credential-like values such as labeled passwords, API keys, bearer tokens, and private-key blocks; do not use Nova's memory as a secret store.

### Launch modes

- `python main.py` — full-screen Textual UI (default)
- `python main.py --prompt-toolkit` — prompt_toolkit input with slash-command completion
- `python main.py --rich` — legacy Rich prompt interface

The Textual UI keeps agent execution in a worker so a slow local model does not freeze the interface. `prompt_toolkit` is an alternate CLI, not embedded inside Textual; both front ends use the same Nova core.

---

# ✦ Project Structure

A simplified project structure:

```text
nova-agent/
│
├── agent/
│   └── core.py
│
├── model/
│   └── ollama.py
│
├── planner.py
│
├── memory/
│   └── extractor.py
│
├── tools/
│   ├── __init__.py
│   ├── registry.py
│   ├── filesystem.py
│   ├── terminal.py
│   └── web.py
│
├── projects/
│
├── main.py
│
└── README.md
```

---

# ✦ Tool Registry

Tools are registered through a central registry.

Conceptually:

```python
registry.register(
    "terminal",
    "Execute commands in the projects or desktop workspace",
    terminal.run
)
```

This allows Nova to discover available capabilities without hardcoding every tool directly into the agent.

---

# ✦ Filesystem Workspace

Nova separates its working locations.

Supported locations include:

```text
projects
desktop
```

The project workspace is protected against paths escaping the allowed root.

For example:

```text
projects/
├── calculator/
├── experiments/
└── test_project/
```

Nova can create, read and modify files inside its allowed workspace.

---

# ✦ Terminal

Nova can execute commands through its terminal tool.

Example:

```text
python calculator.py
```

Terminal results include information such as:

```text
Exit code
Working directory
STDOUT
STDERR
STATUS
```

This allows the planner to determine whether an operation actually succeeded.

---

# ✦ Planning

Nova uses a planner to transform a user request into actionable steps.

Example:

```json
{
  "goal": "Create a calculator project",
  "steps": [
    {
      "description": "Create the calculator file"
    },
    {
      "description": "Run the calculator"
    },
    {
      "description": "Fix any errors"
    }
  ]
}
```

After tool execution, the planner can re-evaluate the plan using the real tool result.

Completed steps are preserved.

---

# ✦ Re-planning

Re-planning is one of Nova's main architectural features.

If a tool succeeds:

```text
Tool
 ↓
Success
 ↓
Planner
 ↓
Mark step completed
 ↓
Continue
```

If a tool fails:

```text
Tool
 ↓
Failure
 ↓
Planner
 ↓
Analyze result
 ↓
Create corrective step
 ↓
Try again
```

This makes Nova closer to an agent than a traditional chatbot.

---

# ✦ Evidence-Based Self-Reflection

After a run, Nova audits the requested goal against the plan's final state and the current run's verifier records. The reflection report tracks:

- Whether the runtime claimed completion
- Planned steps marked completed versus steps still pending
- Confirmed, failed, and unverifiable tool outcomes
- A short explanation for why full completion is or is not supported
- Follow-up candidates when work remains

A computer task is not treated as complete merely because the router says it is done: every planned step must be marked complete and have corresponding confirmed verifier evidence. The latest audit is available in the runtime execution state as `last_reflection`.

Self-reflection does not blindly replay failed actions. Failed or unverifiable calls are already passed to Nova's bounded re-planning loop; any retry must be selected by the planner and pass the normal permission, input-validation, and verification checks. This avoids repeating potentially destructive operations just to make a task appear complete.

The reflection is based on observable state, not a free-form model claim, and it does not expose private model reasoning.

---

# ✦ Memory

Nova includes a memory extraction component.

Memory extraction is intentionally conservative.

The extractor is instructed to:

```text
Do not infer.
Do not guess.
Do not invent.
```

Only explicitly stated information that may be useful in future conversations should become memory.

Example:

```json
{
  "memories": [
    {
      "category": "profile",
      "key": "user_name",
      "value": "..."
    }
  ]
}
```

---

# ✦ Model Configuration

Nova currently uses:

```text
Ollama
└── qwen2.5:3b
```

The model configuration can be changed in the Ollama brain implementation.

The architecture is intentionally separated so the model layer does not contain the agent's tool logic.

---

# ✦ Installation

### 1. Install the core Python dependencies

From the repository root, run:

```bash
python -m pip install -r requirements.txt
```

This installs the dependencies needed for the default Textual interface and the prompt_toolkit/Rich alternatives without forcing the large image-generation or desktop-GUI packages onto every installation.

### 2. Install optional features only when you need them

```bash
python -m pip install -r requirements-optional.txt
```

These extras support desktop automation, OCR, the separate PySide6 GUI, and local Stable Diffusion image generation. Image generation also requires a compatible local model; see `NOVA_IMAGE_MODEL_PATH` in the image-generation tool documentation. OCR via `pytesseract` additionally requires the Tesseract OCR application to be installed on your operating system.

### 3. Install and start Ollama

Make sure Ollama is installed and running, then pull the default model:

```bash
ollama pull qwen2.5:3b
```

You can select another installed model with the `NOVA_MODEL` environment variable.

---

# ✦ Running Nova

Start the agent with:

```bash
python main.py
```

You should see:

```text
✦ NOVA   LOCAL AI AGENT
● LOCAL   ● TOOLS ENABLED   ● PRIVATE

Nova is ready.
```

Then simply type a request.

Example:

```text
› Create a Python calculator project
```

---

# ✦ Commands

Nova provides several terminal commands:

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/clear` | Clear the terminal |
| `/reset` | Reset the terminal view |
| `/exit` | Exit Nova |
| `quit` | Exit Nova |

---

# ✦ Design Principles

Nova is being developed around several principles.

### Local First

The core agent should be able to operate locally through local models and tools.

### Modular

The model, planner, memory system and tools are separated.

### Real Tool Results

Nova should never assume a tool succeeded.

### Re-planning

The agent should be able to adapt when a task does not go as expected.

### Safe Workspace

Filesystem operations should remain inside controlled workspaces.

### Transparent Activity

The terminal UI should show useful high-level activity without exposing private chain-of-thought.

### Extensible

New tools should be addable without rewriting the entire agent. Tool permissions and descriptions are attached to registry entries so planning can discover capabilities dynamically.

---

# ✦ Current Architecture

```text
                    ┌─────────────────┐
                    │      USER       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    NOVA CORE    │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       ┌─────────────┐               ┌─────────────┐
       │   PLANNER   │               │   MEMORY    │
       └──────┬──────┘               └─────────────┘
              │
              ▼
       ┌─────────────┐
       │ TOOL SYSTEM │
       └──────┬──────┘
              │
      ┌───────┼────────┬─────────┐
      ▼       ▼        ▼         ▼
   WEB      TERMINAL  FILES    DIRECTORIES
   SEARCH             │
      │               │
      └───────┬───────┘
              ▼
        REAL TOOL RESULT
              │
              ▼
          RE-PLANNER
              │
        ┌─────┴─────┐
        │           │
      DONE        CONTINUE
        │           │
        ▼           └──────────────┐
     RESPONSE                     │
                                  ▼
                              NEXT TOOL
```

---

# ✦ Example

User:

```text
Create a Python calculator project,
run it, and fix any errors.
```

Nova:

```text
PLAN
  ↓
Create calculator.py
  ↓
WRITE
  ↓
Run calculator
  ↓
TERMINAL
  ↓
Inspect real output
  ↓
Error?
 ├── YES → Fix file → Run again
 └── NO  → Complete
  ↓
FINAL RESPONSE
```

---

# ✦ Development Direction

Nova is designed as a long-term project.

Potential future capabilities include:

- Better autonomous planning
- More reliable tool selection
- Better error recovery
- Persistent knowledge
- More powerful coding workflows
- Git integration
- Better web research
- Improved terminal interaction
- Richer project management
- Better local model support
- More advanced agent loops
- Improved UI and observability

The architecture is intentionally being built incrementally so each capability can be tested independently.

---

# ✦ Philosophy

Nova is not intended to be just another chatbot.

The goal is to build a local AI system that can:

```text
Understand
   ↓
Plan
   ↓
Act
   ↓
Observe
   ↓
Adapt
   ↓
Finish
```

One tool at a time.

---

# ✦ Codex / Claude-Style Terminal UI

Nova now has a redesigned Rich terminal interface focused on chat-first interaction and agent observability.

The UI includes:

- Persistent **You / Nova** chat blocks
- A live **ACTIVITY** panel while Nova is working
- A persistent **RUN TRACE** after each request
- High-level model activity such as `PLAN`, `WEB`, `GIT`, `TERM`, `READ`, `WRITE`, `THINK`, and `DONE`
- No private chain-of-thought is displayed
- Configured local model indicator
- Capability controls for **Web Search**, **Git**, and **PC Use**
- Session reset and screen controls
- Permission state visible directly in the header

### Capability controls

```text
/web            Toggle web-search access
/git            Toggle Git / repository access
/pc             Toggle terminal + filesystem access
/permissions    Show current capability states
/reset          Start a fresh Nova session
```

The permission controls are enforced by the agent core as well as the router. A disabled capability is removed from the model's available tool set and blocked again before execution.

The UI reports **what Nova is doing**, not the model's hidden reasoning.


---


---

# ✦ AI Assistance

Taji-Soft team uses AI tools to accelerate development speed, improve code quality, and explore new ideas faster.

We believe AI assistance is a natural part of modern software development — it helps us iterate quickly, catch issues early, and focus on architecture and design rather than repetitive implementation.

### AI models used in this project

| Model | Provider | Used for |
|---|---|---|
| **Claude Sonnet 4.6** | Anthropic | Architecture design, code generation, debugging, documentation |
| **GPT 5.6 Luna** | OpenAI | Code review, alternative implementations, research |
| **GLM 5.2** | Zhipu AI | Experimentation, multilingual support, alternative perspectives |

> All AI-generated code is reviewed, tested, and adapted by the Taji-Soft team before being committed to the project.

---
## License
This project is licensed under the MIT License.



---

# ✦ Runtime Self-Inspection

The Rich terminal interface includes evidence-based inspection commands:

| Command | What it shows |
|---|---|
| `/status` | Fast local runtime summary; does not contact Ollama |
| `/self` | Nova identity, Python/platform, context/output budgets, live core components, registered tools, permissions, and Ollama model metadata |
| `/model` | On-demand Ollama metadata such as parameter count, architecture, quantization, model context length, and reported capabilities |
| `/tools` | Live tool registry with capability and permission state |
| `/doctor` | Runtime configuration checks and Ollama/model-list diagnostics |
| `/permissions` | Current web, Git, and PC permission toggles |
| `/help` | Full command list |

Model metadata is read from Ollama, not guessed from a model tag. If Ollama does not provide a value, Nova displays `Unknown`. A model appearing in metadata or a local model list does not by itself prove that text generation is working. Parameter count refers to the configured language model, not to the number of parameters in Nova's Python agent code.

The UI shows high-level activity and observable results. It does not expose private model reasoning.
