# Changelog

All notable changes to Nova are documented in this file.

## 2.3 — 2026-11-11

### Added
- **Agentic tool loop**: Nova now drives tools through a native tool-calling loop in the main UI (`agent/tool_loop.py`), chaining multiple tool calls autonomously.
- **NoviqX GitHub App integration (MCP)**: bring-your-own-App model — MCP server (`integrations/noviqx/mcp_server.py`), registry tools, RS256 JWT → installation-token auth chain with caching and auto-refresh on 401, and SHA-locked writes (read-before-write with optimistic locking).
- **First-run setup wizard** (`ui/noviqx_setup_wizard.py`): 4 steps — intro, create-your-own-App instructions, credentials form with live validation, and a real connection test. Includes a "Never show this again" button and a Settings menu entry. Credentials persist in `~/.nova/noviqx.json` (mode 0600, stores only App ID / Installation ID / .pem path — the private key never leaves your disk).
- **NoviqX smoke test** (`scripts/noviqx_smoke_test.py`): exercises the full real integration — JWT → installation token → repo metadata → SHA-locked write round-trip.
- **Conversation history as real chat turns**: short-term history is now sent to the model as proper alternating user/assistant messages (12-message / 6,000-character budget, tool entries excluded) instead of a flattened transcript inside the context block.

### Fixed
- **Short-term memory / pronoun resolution**: after discussing a topic (e.g. the Greek letter Sigma), follow-up questions like "does *this* have applications in AI?" failed to bind "this" to the previous topic. Fixed by passing history as real chat turns and instructing the model to resolve references against them.
- **Wizard layout**: old widgets stayed visible from step 3 onward because `deleteLater()` is deferred; widgets are now detached immediately on step change.
- **Math parser**: superscript minus rendered as a plus (`e⁺ˣ` instead of `e⁻ˣ`), and inline code lost a following space (`` `\sigma(x)`and `` instead of `` `\sigma(x)` and ``).
- **UI stability**: stopped streaming-protocol floods and hardened entry points (PR #50).
- **Security hardening** of tool execution (PR #48) and major logic fixes across agent core, model providers and memory (PR #49).

### Tests
- 432 passing, 4 skipped — including 12 new NoviqX settings/security tests and 5 conversation-history regression tests.

## 2.2 — 2026-11-08

- Versions before 2.3 predate this changelog; see the commit history for details.
