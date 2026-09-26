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

Current model:

```text
qwen2.5:3b
```

The model is used for:

- Planning
- Re-planning
- Memory extraction
- Tool decisions
- Final responses

---

### 🛠 Tool System

Nova currently supports several tools:

| Tool | Purpose |
|---|---|
| `web_search` | Search the public web |
| `terminal` | Execute terminal commands |
| `list_files` | List files and directories |
| `read_file` | Read text files |
| `write_file` | Create or overwrite files |
| `create_directory` | Create directories |

The tool system is registry-based, allowing additional tools to be added without rebuilding the entire agent.

---

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

The important part is that Nova receives the **real result** of each tool execution.

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

Nova includes a Rich-based terminal interface designed to make agent activity visible without exposing internal chain-of-thought.

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

Install the required Python packages.

For example:

```bash
pip install ollama rich
```

Make sure Ollama is installed and running.

Then pull the model:

```bash
ollama pull qwen2.5:3b
```

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

New tools should be addable without rewriting the entire agent.

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

## License
This project is licensed under the MIT License.

