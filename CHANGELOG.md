# Changelog

All notable changes to Nova are documented in this file.

## 2.3 — 2026-11-11

### Added
- **Agentic tool loop**: Nova now drives tools through a native tool-calling loop in the main UI (`agent/tool_loop.py`), chaining multiple tool calls autonomously.
- **Live activity indicator**: a small chip above the message composer shows what Nova is doing right now in human words — Thinking, Searching the web, Reading the file, Writing — with a pulsing dot, instead of an opaque wait. Tool execution publishes `ACTIVITY:` events (`agent/activity.py` maps every registry tool to a readable phrase); the terminal UIs show the same phrases in their status line.
- **NoviqX GitHub App integration (MCP)**: bring-your-own-App model — MCP server (`integrations/noviqx/mcp_server.py`), registry tools, RS256 JWT → installation-token auth chain with caching and auto-refresh on 401, and SHA-locked writes (read-before-write with optimistic locking).
- **First-run setup wizard** (`ui/noviqx_setup_wizard.py`): 4 steps — intro, create-your-own-App instructions, credentials form with live validation, and a real connection test. Includes a "Never show this again" button and a Settings menu entry. Credentials persist in `~/.nova/noviqx.json` (mode 0600, stores only App ID / Installation ID / .pem path — the private key never leaves your disk).
- **NoviqX smoke test** (`scripts/noviqx_smoke_test.py`): exercises the full real integration — JWT → installation token → repo metadata → SHA-locked write round-trip.
- **Conversation history as real chat turns**: short-term history is now sent to the model as proper alternating user/assistant messages (12-message / 6,000-character budget, tool entries excluded) instead of a flattened transcript inside the context block.

### Fixed
- **Local model 503 root cause — system proxy intercepting localhost**: the retry fix alone did not clear every 503, because the error body was empty — Ollama itself always answers with a JSON body, so the 503 was produced by a middlebox. The Ollama Python client is built on httpx, which routes **every** `http://` request through `HTTP_PROXY`/`HTTPS_PROXY` (no loopback exception, unlike the Go client the Ollama CLI uses), so VPN/proxy tools answered Nova's requests to `localhost:11434` with a bare 503 even while `ollama run` worked in the same terminal. Nova now adds `localhost`, `127.0.0.1` and `::1` to `NO_PROXY` at startup (user entries preserved; remote providers keep using the proxy), grows the retry budget to 6 attempts (~31s — enough for cold model loads), and the failure message now points at the proxy when the 503 body is empty (PR #55).
- **Local (Ollama) 503 failures**: with a local model, tool conversations could abort with "the tool interaction failed: ResponseError (status code: 503)" whenever Ollama was still loading the model or its runner was busy. Ollama chat calls now retry transient 5xx errors with backoff (1s → 2s → 4s; configurable via `NOVA_OLLAMA_RETRIES`, default 4 attempts) across all four brain paths (plain, streamed, tool-turn, streamed tool-turn), streaming turns only retry before the first token so nothing is duplicated on screen. If the server still does not recover, Nova explains the cause and suggests `ollama ps` instead of dumping the raw error.
- **Short-term memory / pronoun resolution**: after discussing a topic (e.g. the Greek letter Sigma), follow-up questions like "does *this* have applications in AI?" failed to bind "this" to the previous topic. Fixed by passing history as real chat turns and instructing the model to resolve references against them.
- **Wizard layout**: old widgets stayed visible from step 3 onward because `deleteLater()` is deferred; widgets are now detached immediately on step change.
- **Math parser**: superscript minus rendered as a plus (`e⁺ˣ` instead of `e⁻ˣ`), and inline code lost a following space (`` `\sigma(x)`and `` instead of `` `\sigma(x)` and ``).
- **UI stability**: stopped streaming-protocol floods and hardened entry points (PR #50).
- **Security hardening** of tool execution (PR #48) and major logic fixes across agent core, model providers and memory (PR #49).

### Tests
- 465 passing, 5 skipped — including 12 new NoviqX settings/security tests, 5 conversation-history regression tests, 9 tool-activity status regression tests, and 18 Ollama transient-503/proxy-bypass tests.

## 2.2 — 2026-11-08

- Versions before 2.3 predate this changelog; see the commit history for details.
