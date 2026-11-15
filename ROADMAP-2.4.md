# Roadmap 2.4 — Agent-grade Nova

Goal: turn Nova from "a chat that can call tools" into a real agent — the kind
of loop, planning, research and file precision Claude or ChatGPT ship — while
keeping the local-first philosophy (everything must keep working on Ollama).

The skeleton already exists in the codebase; 2.4 is about completing it:

| Pillar | Today | 2.4 target |
| --- | --- | --- |
| Tool loop | `agent/tool_loop.py`, `MAX_CALLS_PER_TURN = 6`, sequential, hard truncation | long autonomous runs with rolling compaction, parallel-safe tools, timeouts, structured error feedback |
| Plan | `agent/planner.py` (create/replan/verify, 1500 lines) but plan lives inside the planner | one canonical task store, model-managed via a `task_list` tool, rendered live in the UI as a **Plan box** |
| Search | `tools/web.py` — DDG/Bing HTML scraping, single query | a deep-research orchestrator: multi-query, fetch, gap analysis, cited synthesis |
| Files | `tools/filesystem.py` — sandbox, atomic write, edit, delete | paginated numbered reads, uniqueness-checked edits, diff preview |
| Thinking | native `thinking` streaming for reasoning models (`MODEL_THOUGHT_DELTA`) | visible reasoning for **every** model via a `think` scratchpad tool + planner timeline |
| UI | activity chip | activity chip + live Plan box + thinking panel, all fed by one event protocol |

## M1 — Tool loop v2 (`agent/tool_loop.py`)

1. **Raise the cap, add rolling compaction.** `MAX_CALLS_PER_TURN` grows to a
   configurable budget (default ~20). Tool results get a bounded rolling
   window: the last N results are kept verbatim, older ones are replaced by a
   one-line summary (`[tool X on Y → ok, 3.2s]`) so long chains stay in
   context. Truncation of a single huge result stays.
2. **Parallel-safe execution.** Tools declare `parallel_ok` in their
   registry metadata (web search, list, read: yes; write/terminal/desktop: no).
   Independent same-turn calls run concurrently, results re-order deterministically.
3. **Per-call timeout + structured errors.** Every tool call gets a timeout
   (default 120s, override per tool). Failures return structured JSON to the
   model (`{"error": "...", "hint": "..."}`) so it can self-correct instead of
   crashing the turn — mirroring what `_tool_failure_message` does for the user.
4. **Cancellation.** Mid-loop user cancel stops between tool calls (already
   partially supported by the streaming paths — must work through the whole loop).

Tests: the fake-model harness (below) scripts long chains, parallel batches,
a timeout and a self-correcting error path.

## M2 — One task store + the Plan box (the "like your todo panel" feature)

1. **`agent/task_state.py`** — a canonical `TaskList`: ordered items
   `{content, status: pending|in_progress|completed, priority}` plus a
   version counter. One writer API (`set_items`, `update`, `mark_in_progress`)
   that publishes a `TASK_SNAPSHOT:<json>` event through the existing status
   pipeline (the same transport as `ACTIVITY:` and `MODEL_THOUGHT_DELTA:`).
2. **`task_list` registry tool** — the model's own todo tool (validated input
   via the registry's existing validation rules). The tool loop calls it
   whenever the model wants to re-plan itself, exactly like the agent box in
   Claude-style products. Full-replacement semantics on every call, one item
   `in_progress` at a time — validated.
3. **Planner sync.** `planner.create_plan()` seeds the TaskList;
   `update_step()` publishes snapshots; `verify_goal`/`replan` read the same
   store. Two writers (deterministic planner + model self-management), one store.
4. **UI card.** In `App.py`, next to the activity chip: a collapsible
   **Plan** card — title row with "N of M complete", per-item rows with
   ✓ (completed, strikethrough), ▸ pulsing dot (in_progress), ○ (pending).
   Collapsed automatically when all items complete. `textual_app`/`prompt_cli`
   render the snapshot in their status area.
5. **Persistence.** Plans save to `~/.nova/plans/<id>.json`; a session can be
   resumed with its task state.

Tests: store semantics, snapshot events, tool validation, and a UI-less
render function both desktop and TUI share.

## M3 — Planner hardening

1. **Replan budget** (default 3) so the planner can never loop forever;
   after the budget it degrades to a clear failure message.
2. **Parallel steps** where declared dependencies allow (`"after": [...]`
   already normalized by `_normalize_steps` — execute independent waves).
3. **Automatic verify gate**: `verify_goal` runs before the final answer on
   any plan with ≥2 completed steps, not only when asked.

## M4 — File tools to Claude grade (`tools/filesystem.py`)

1. **`read_file` with `offset`/`limit` and line numbers** — big files are no
   longer read whole; output is numbered so edits can reference lines.
2. **`edit_file` uniqueness check** — exact old-string → new-string
   replacement that refuses when the old string matches more than once
   (or zero times), with a clear hint; keeps the existing atomic write.
3. **Diff preview** — writes and edits can emit a unified diff event
   (`DIFF_PREVIEW:<text>`) so the UI can show what is about to change
   before it changes; dangerous deletes stay behind the M1 confirmation flow.

## M5 — Thinking panel for ALL models

1. Native `thinking` streaming already works for reasoning models — keep it.
2. **`think` scratchpad tool** (Anthropic-style): any model can call it mid
   loop; content streams into the thinking panel as `MODEL_THOUGHT_DELTA`.
   This gives every local model a visible reasoning trace.
3. Planner step transitions publish timeline entries into the same panel
   (`Plan: step 2/5 — searching sources`), replacing the current rule that
   planner summaries are never displayed (`_publish_thinking_process`).

## M6 — Deep research mode

1. **`tools/web.py` upgrades**: readability-style main-content extraction for
   fetched pages, per-domain rate limiting, response caching, and a standalone
   `fetch_page` tool beside `web_search`.
2. **Research orchestrator in `agent/router.py`**: decompose the question →
   generate 3-5 diverse queries → parallel search → fetch top pages → extract
   → gap analysis ("what is still unknown?") → 1-2 more rounds → synthesis
   **with citations**. Progress is published through the Plan box, so the user
   sees "Searching sources", "Reading 4/8", "Synthesizing".
3. Result format: answer + per-claim source list; failures degrade to plain
   search instead of erroring.

## Model guidance

Agent-grade loops on Ollama need tool-calling discipline: recommend
`qwen3:14b` or better as the default agent model (document in README), keep
the remote providers first-class as today. The loop machinery (validation,
compaction, structured errors) is designed to compensate for weaker local
tool calling.

## Test strategy

A scripted fake-model harness (pattern proven by
`tests/e2e_proxy_bypass_child.py`): a deterministic scripted model drives the
real tool loop end-to-end — long chains, parallel batches, timeouts,
task_list updates, file edits — asserting final state without any live model
or network. Each milestone ships with its slice of that harness.

## Milestone order

M1 → M2 → M4 (foundation + visible wins) → M5 → M3 → M6. Roughly two
releases' worth of work; each milestone is one PR with green CI before the
next starts.
