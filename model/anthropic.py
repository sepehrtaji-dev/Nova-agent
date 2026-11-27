"""Native Anthropic Messages API adapter for Nova's model interface."""
from __future__ import annotations
import json
import os
import ssl
import urllib.error
import urllib.request
from model.remote import RemoteBrainError, _scrub, _DEFAULT_SYSTEM_PROMPT, _iter_stream_lines


class AnthropicBrain:
    """Anthropic Messages API adapter with native tool-use round trips."""
    def __init__(self, model=None, api_key=None, base_url=None, timeout=120):
        self.model = str(model or os.getenv("NOVA_API_MODEL", "")).strip()
        self.api_key = str(api_key or os.getenv("NOVA_API_KEY", "")).strip()
        self.base_url = str(base_url or os.getenv("NOVA_API_BASE_URL", "https://api.anthropic.com")).strip().rstrip("/")
        self.timeout = float(timeout or 120)
        self.last_error = None

    def is_configured(self):
        return bool(self.model and self.api_key and self.base_url)

    def configuration_help(self):
        return "Set an Anthropic API key and Claude model name in Settings."

    def describe(self):
        return f"Anthropic Claude model '{self.model}' via Messages API"

    @staticmethod
    def _extract_text(data):
        blocks = data.get("content", []) if isinstance(data, dict) else []
        return "\n".join(str(b.get("text", "")) for b in blocks
                          if isinstance(b, dict) and b.get("type") == "text").strip()

    @staticmethod
    def _extract_thinking_summary(data):
        blocks = data.get("content", []) if isinstance(data, dict) else []
        return "\n".join(
            str(block.get("thinking", "")).strip()
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "thinking"
            and isinstance(block.get("thinking"), str)
            and block.get("thinking", "").strip()
        ).strip()

    @staticmethod
    def _thinking_options(payload, options):
        if isinstance(options, dict) and options.get("show_reasoning"):
            # Anthropic returns a summarized thinking block, not raw private
            # chain-of-thought, when display is set to summarized.
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}

    def _request(self, payload):
        if not self.is_configured():
            raise RemoteBrainError("Anthropic provider is not configured. " + self.configuration_help())
        request = urllib.request.Request(
            f"{self.base_url}/v1/messages", data=json.dumps(payload).encode("utf-8"),
            method="POST", headers={
                "content-type": "application/json", "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01", "accept": "application/json",
                "user-agent": "NovaAgent/2.3",
            })
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=ssl.create_default_context()) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                detail = ""
            finally:
                exc.close()
            self.last_error = _scrub(detail, self.api_key)
            raise RemoteBrainError(f"Anthropic API returned HTTP {exc.code}. Check the API key, model name, and account access.") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = _scrub(str(exc), self.api_key)
            raise RemoteBrainError(f"Anthropic API request failed: {self.last_error}", transient=True) from exc
        except json.JSONDecodeError as exc:
            raise RemoteBrainError("Anthropic returned an invalid JSON response.") from exc
        if not isinstance(data, dict) or data.get("type") == "error":
            detail = data.get("error", {}).get("message", "unexpected response") if isinstance(data, dict) else "unexpected response"
            raise RemoteBrainError("Anthropic API error: " + _scrub(detail, self.api_key))
        return data

    @staticmethod
    def _convert_tools(tools):
        result = []
        for item in tools or []:
            if not isinstance(item, dict):
                continue
            fn = item.get("function", item)
            if isinstance(fn, dict) and fn.get("name"):
                result.append({"name": fn["name"], "description": str(fn.get("description", "")),
                               "input_schema": fn.get("parameters") or {"type": "object", "properties": {}}})
        return result

    @staticmethod
    def _convert_messages(messages):
        result = []
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role == "tool":
                block = {"type": "tool_result", "tool_use_id": str(item.get("tool_call_id", "")),
                         "content": str(item.get("content", ""))}
                if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                    result[-1]["content"].append(block)
                else:
                    result.append({"role": "user", "content": [block]})
            elif role == "assistant" and isinstance(item.get("tool_calls"), list):
                provider_content = item.get("provider_content")
                if isinstance(provider_content, list) and provider_content:
                    result.append({"role": "assistant", "content": provider_content})
                    continue
                blocks = []
                if item.get("content"):
                    blocks.append({"type": "text", "text": str(item["content"])})
                for call in item["tool_calls"]:
                    fn = call.get("function", {}) if isinstance(call, dict) else {}
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    blocks.append({"type": "tool_use", "id": str(call.get("id", "tool_call")),
                                   "name": str(fn.get("name", "")),
                                   "input": args if isinstance(args, dict) else {}})
                result.append({"role": "assistant", "content": blocks})
            elif role in {"user", "assistant"}:
                text = str(item.get("content") or "")
                if result and result[-1]["role"] == role:
                    # The Anthropic Messages API requires strict user/assistant
                    # alternation; two consecutive same-role messages return
                    # HTTP 400. Merge into one message with multiple text blocks.
                    if text:
                        previous = result[-1]
                        if isinstance(previous["content"], str):
                            previous["content"] = [{"type": "text", "text": previous["content"]}]
                        previous["content"].append({"type": "text", "text": text})
                else:
                    result.append({"role": role, "content": text})
        return result

    def generate(self, prompt, system_prompt=None, json_mode=False, options=None):
        system = str(system_prompt or _DEFAULT_SYSTEM_PROMPT)
        if json_mode:
            system += "\nReturn only valid JSON."
        payload = {"model": self.model, "max_tokens": 4096, "system": system,
                   "messages": [{"role": "user", "content": str(prompt)}]}
        if isinstance(options, dict):
            if "max_tokens" in options:
                payload["max_tokens"] = int(options["max_tokens"])
            elif "num_predict" in options:
                payload["max_tokens"] = int(options["num_predict"])
            for key in ("temperature", "top_p"):
                if key in options:
                    payload[key] = options[key]
        return self._extract_text(self._request(payload))

    def c_gen(self, prompt, system_prompt=None, **kwargs):
        return self.generate(prompt, system_prompt=system_prompt, **kwargs)

    def generate_tool_turn(self, messages, tools, system_prompt=None, options=None, **kwargs):
        payload = {"model": self.model, "max_tokens": 4096,
                   "system": str(system_prompt or _DEFAULT_SYSTEM_PROMPT),
                   "messages": self._convert_messages(messages),
                   "tools": self._convert_tools(tools)}
        if isinstance(options, dict):
            if "max_tokens" in options:
                payload["max_tokens"] = int(options["max_tokens"])
            elif "num_predict" in options:
                payload["max_tokens"] = int(options["num_predict"])
            for key in ("temperature", "top_p"):
                if key in options:
                    payload[key] = options[key]
        self._thinking_options(payload, options)
        try:
            data = self._request(payload)
        except RemoteBrainError:
            if "thinking" not in payload:
                raise
            payload.pop("thinking", None)
            data = self._request(payload)
        calls = []
        for block in data.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"id": block.get("id", ""), "type": "function",
                              "function": {"name": block.get("name", ""),
                                           "arguments": json.dumps(block.get("input", {}), ensure_ascii=False)}})
        return {
            "content": self._extract_text(data),
            "thinking": self._extract_thinking_summary(data),
            "provider_content": data.get("content", []),
            "tool_calls": calls,
            "finish_reason": "tool_calls" if calls else data.get("stop_reason", "stop"),
        }

    def generate_stream(
        self, prompt, on_token, system_prompt=None, json_mode=False, options=None,
        on_thought_delta=None, cancel_event=None,
    ):
        """Stream answer text and summarized thinking blocks from Anthropic."""
        if not self.is_configured():
            raise RemoteBrainError(
                "Anthropic provider is not configured. " + self.configuration_help()
            )
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": str(system_prompt or _DEFAULT_SYSTEM_PROMPT),
            "messages": [{"role": "user", "content": str(prompt)}],
            "stream": True,
        }
        if isinstance(options, dict):
            if "max_tokens" in options:
                payload["max_tokens"] = int(options["max_tokens"])
            elif "num_predict" in options:
                payload["max_tokens"] = int(options["num_predict"])
            for key in ("temperature", "top_p"):
                if key in options:
                    payload[key] = options[key]
        self._thinking_options(payload, options)

        def consume():
            text_parts = []
            request = urllib.request.Request(
                f"{self.base_url}/v1/messages",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "accept": "text/event-stream",
                    "user-agent": "NovaAgent/2.3",
                },
            )
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=ssl.create_default_context()
            ) as response:
                for raw_line in _iter_stream_lines(response, cancel_event, self.timeout):
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "content_block_delta":
                        continue
                    delta = event.get("delta", {})
                    if not isinstance(delta, dict):
                        continue
                    if delta.get("type") == "thinking_delta":
                        summary = delta.get("thinking", "")
                        if summary and callable(on_thought_delta):
                            on_thought_delta(str(summary))
                    elif delta.get("type") == "text_delta":
                        token = delta.get("text", "")
                        if token:
                            token = str(token)
                            text_parts.append(token)
                            if callable(on_token):
                                on_token(token)
            return "".join(text_parts)

        try:
            return consume()
        except urllib.error.HTTPError as exc:
            # Older Claude models may not support adaptive thinking. Retry the
            # same answer request without the optional summary channel.
            if "thinking" in payload and exc.code == 400:
                try:
                    exc.close()
                except Exception:
                    pass
                payload.pop("thinking", None)
                try:
                    return consume()
                except urllib.error.HTTPError as retry:
                    detail = ""
                    try:
                        detail = retry.read().decode("utf-8", "replace")[:500]
                    except Exception:
                        pass
                    finally:
                        retry.close()
                    self.last_error = _scrub(detail, self.api_key)
                    raise RemoteBrainError(
                        f"Anthropic API returned HTTP {retry.code}: {self.last_error}"
                    ) from retry
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            finally:
                exc.close()
            self.last_error = _scrub(detail, self.api_key)
            raise RemoteBrainError(
                f"Anthropic API returned HTTP {exc.code}: {self.last_error}",
                transient=exc.code in (408, 409, 429, 500, 502, 503, 504),
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.last_error = _scrub(str(exc), self.api_key)
            raise RemoteBrainError(
                f"Anthropic stream failed: {self.last_error}", transient=True
            ) from exc
