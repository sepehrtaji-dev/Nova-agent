# Native agentic tool loop

Nova's bundled Ollama and OpenAI-compatible providers expose a shared
generate_tool_turn interface. NovaCore uses it when the configured backend
advertises native tool-call support.

## Control flow

1. Nova sends the user request, bounded session context, and the currently
   enabled tool definitions to the model.
2. The model returns either ordinary assistant text or structured function
   calls.
3. Nova validates every call against the live registry, the declared JSON
   schema, and the current capability permissions.
4. Nova runs registered input preparation where configured, executes the
   handler, and asks the verifier to inspect the result.
5. Nova appends an assistant tool-call message and one result message per call
   to the conversation sent on the next model turn.
6. The model chooses another tool or returns its final answer.

There is no mandatory second planner pass after each successful read. The
model receives the actual result and decides whether another operation is
needed. This avoids turning every file read into a separate plan-rewrite
request.

## Provider compatibility

- OpenAI-compatible chat completions receive tools, tool_choice: auto, and
  standard assistant tool_calls / tool_call_id result messages.
- Ollama receives the same function definitions and assistant tool-call
  messages, while result messages are adapted to Ollama's tool_name format.
- The EffortAwareBrain wrapper forwards the selected reasoning effort to
  either provider.
- Backends without generate_tool_turn keep the existing planner/router path.

Native tool-call requests are not retried automatically. A timeout can happen
after a provider has generated a tool call, so blindly replaying an ambiguous
request can duplicate a side effect. The caller receives a provider error and
can report the failure instead.

## Native Ollama thinking channel

For Ollama models that expose native thinking, Nova requests the channel through
the `think` argument on the same `ollama.chat()` call that performs each
agentic tool-loop turn. It does not issue a separate "think" request and then
re-run the turn for tools.

- Nova probes the selected model with `ollama.show()` and respects the
  model-advertised `thinking.values` and default.
- The Ollama adapter keeps `message.thinking` separate from
  `message.content`, and streams them through separate callbacks.
- `EffortAwareBrain` forwards the native thought callback and resolves the
  selected effort to a value supported by that model. The Off setting sends
  `think=False`.
- The desktop Thinking panel displays only native model thinking deltas.
  Planner, permission, tool-execution, and verification status events remain
  status/activity updates and are not presented as model reasoning.
- Models that do not expose a native thinking channel may return no thought
  deltas. Nova must not manufacture placeholder reasoning to fill the panel.

The native field is optional and model-dependent. An empty thinking field is
not evidence that a model did not perform internal computation; it means Nova
was not given a native trace to display.

## Execution and safety invariants

- Only tools in the current allowed-tool set are exposed to the model.
- Tool names and arguments are checked again at execution time; a model response
  is never treated as permission.
- Input preparation runs before final schema validation, so tools such as
  write_file can generate missing content through the existing file-content
  service and then validate the completed payload.
- Tool handlers run in Nova's process. Results are returned as data and are
  explicitly treated as untrusted content by the system prompt.
- Verifier status is kept separate from the tool's text output. The model may
  report an operation as confirmed only when Nova supplies verifier evidence.
- Calls in a single assistant turn execute serially. This preserves filesystem
  and Git ordering even when the model requests multiple independent calls.
- Tool output is bounded to 40,000 characters per result. The default loop is
  bounded by NOVA_MAX_STEPS (12 rounds).
- Repeated calls are not globally deduplicated: a model may legitimately need
  to read a file again after editing it. The round limit bounds repetition.

## Tests

tests/test_tool_calling_loop.py covers read → write → read → final answer
round trips, disabled-tool rejection, schema validation feedback, and
malformed-argument recovery. tests/test_remote_brain.py covers remote
function-call payloads and provider-specific message serialization.
