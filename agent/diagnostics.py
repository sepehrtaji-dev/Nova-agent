"""Runtime diagnostics and evidence-based capability status for Nova.

Diagnostics report observable configuration and recent verifier evidence. A
registered tool is not proof that it works, and a listed Ollama model is not
proof that it is currently loaded or can generate a response.
"""
import re


class RuntimeDiagnostics:
    """Inspect Nova's live configuration without executing user-facing tools."""

    @staticmethod
    def _tool_status(core, tool_name):
        state = getattr(core, "execution_state", None)
        entries = state.get("verified_tools", []) if isinstance(state, dict) else []
        if not isinstance(entries, list):
            return "untested", "No usable execution history."

        for entry in reversed(entries):
            if not isinstance(entry, dict) or entry.get("tool") != tool_name:
                continue
            verification = entry.get("verification", {})
            if not isinstance(verification, dict):
                return "untested", "Latest result has no structured verification."
            status = str(verification.get("status", "unverifiable")).strip().lower()
            evidence = str(verification.get("message") or verification.get("evidence") or "").strip()
            if status == "confirmed":
                return "verified", evidence or "Latest recorded action was verifier-confirmed."
            if status == "failed":
                return "failed", evidence or "Latest recorded action failed verification."
            return "untested", evidence or "Latest recorded action could not be verified."
        return "untested", "No recorded verification for this tool."

    def capability_map(self, core):
        registry = getattr(core, "tools", None)
        registered = getattr(registry, "tools", {}) or {}
        access = getattr(core, "access", {}) or {}
        capabilities = []

        if not isinstance(registered, dict):
            registered = {}

        for name, raw in sorted(registered.items()):
            data = raw if isinstance(raw, dict) else {}
            capability = str(data.get("capability", "pc"))
            enabled = bool(access.get(capability, True))
            observed_status, evidence = self._tool_status(core, str(name))
            if not enabled:
                status = "disabled"
            else:
                status = observed_status
            capabilities.append({
                "name": str(name),
                "description": str(data.get("description", "")).strip(),
                "capability": capability,
                "enabled": enabled,
                "status": status,
                "evidence": evidence,
            })
        return capabilities

    @staticmethod
    def _probe_ollama(core, list_models=None):
        brain = getattr(core, "brain", None)
        configured = str(getattr(brain, "model", "") or "").strip()
        if not configured:
            return {"status": "not_configured", "detail": "No model name is configured."}

        try:
            if list_models is None:
                import ollama
                list_models = ollama.list
            response = list_models()
        except Exception as exc:
            return {
                "status": "unreachable",
                "detail": f"Ollama model-list request failed ({type(exc).__name__}).",
            }

        if isinstance(response, dict):
            models = response.get("models", [])
        else:
            models = getattr(response, "models", [])
        names = []
        for item in models or []:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
            else:
                name = getattr(item, "name", None) or getattr(item, "model", None)
            if name:
                names.append(str(name))

        if configured in names:
            return {
                "status": "available",
                "detail": f"Configured model '{configured}' appears in the local Ollama model list; generation was not tested.",
            }
        return {
            "status": "missing",
            "detail": f"Configured model '{configured}' was not found in the local Ollama model list.",
        }

    def snapshot(self, core, probe_model=False, list_models=None):
        brain = getattr(core, "brain", None)
        model = str(getattr(brain, "model", "") or "").strip()
        registry = getattr(core, "tools", None)
        registered = getattr(registry, "tools", None)
        access = getattr(core, "access", None)
        state = getattr(core, "execution_state", None)

        checks = []
        checks.append({
            "name": "model_configuration",
            "status": "configured" if model else "failed",
            "detail": f"Configured model: {model}" if model else "No model is configured.",
        })
        checks.append({
            "name": "tool_registry",
            "status": "available" if isinstance(registered, dict) else "failed",
            "detail": f"{len(registered)} tool(s) registered." if isinstance(registered, dict) else "Tool registry is missing or invalid.",
        })
        checks.append({
            "name": "permission_configuration",
            "status": "available" if isinstance(access, dict) else "warning",
            "detail": "Capability permissions are readable." if isinstance(access, dict) else "Capability permissions are missing or invalid.",
        })
        checks.append({
            "name": "execution_history",
            "status": "available" if isinstance(state, dict) else "warning",
            "detail": "Structured execution history is available." if isinstance(state, dict) else "No structured execution history is available.",
        })

        model_check = self._probe_ollama(core, list_models) if probe_model else {
            "status": "not_probed",
            "detail": "Ollama connectivity was not probed; run an explicit self-diagnostic to check it.",
        }
        if probe_model:
            checks.append({
                "name": "ollama",
                "status": "available" if model_check["status"] == "available" else (
                    "failed" if model_check["status"] in {"unreachable", "missing", "not_configured"} else "warning"
                ),
                "detail": model_check["detail"],
            })

        capabilities = self.capability_map(core)
        failed = [item for item in capabilities if item["status"] == "failed"]
        untested = [item for item in capabilities if item["status"] == "untested"]
        disabled = [item for item in capabilities if item["status"] == "disabled"]
        return {
            "checks": checks,
            "model": model_check,
            "capabilities": capabilities,
            "summary": {
                "registered_tools": len(capabilities),
                "verified_tools": sum(item["status"] == "verified" for item in capabilities),
                "failed_tools": len(failed),
                "untested_tools": len(untested),
                "disabled_tools": len(disabled),
            },
        }

    def context(self, core):
        report = self.snapshot(core, probe_model=False)
        lines = ["CAPABILITY MAP (registered/enabled state plus latest recorded verification):"]
        if not report["capabilities"]:
            lines.append("- No tools are registered.")
        for item in report["capabilities"]:
            description = f" — {item['description']}" if item["description"] else ""
            lines.append(
                f"- {item['name']} [{item['capability']}; {item['status']}]{description}"
            )
        lines.append(
            "Status meanings: verified = latest recorded verifier result confirmed; "
            "failed = latest recorded verifier result failed; untested = no confirmation; "
            "disabled = permission currently blocks this tool."
        )
        lines.append("These statuses are historical/runtime evidence, not guarantees of future success.")
        return "\n".join(lines)

    def answer(self, message, core, list_models=None):
        if not isinstance(message, str):
            return None
        normalized = re.sub(r"\s+", " ", message.strip().casefold())
        if not normalized:
            return None
        request = bool(re.search(
            r"\b(?:diagnose yourself|run (?:a )?self[- ]?diagnostic|self[- ]?diagnostics?|"
            r"check your (?:own )?(?:status|health|runtime)|are you working properly|"
            r"run a health check|check your system)\b|"
            r"(?:خودت رو بررسی کن|خودت را بررسی کن|خودتشخیصی|وضعیت خودت رو بررسی کن|سلامت خودت رو بررسی کن|وضعیت سیستم رو بررسی کن)",
            normalized,
        ))
        if not request:
            return None

        report = self.snapshot(core, probe_model=True, list_models=list_models)
        summary = report["summary"]
        lines = ["Nova self-diagnostic report:"]
        for check in report["checks"]:
            lines.append(f"- {check['name']}: {check['status']} — {check['detail']}")
        lines.append(
            "- Capability summary: "
            f"{summary['registered_tools']} registered, "
            f"{summary['verified_tools']} recently verified, "
            f"{summary['failed_tools']} last verification failed, "
            f"{summary['untested_tools']} untested, "
            f"{summary['disabled_tools']} disabled."
        )
        failed = [item for item in report["capabilities"] if item["status"] == "failed"]
        if failed:
            lines.append("Tools with failed latest verification: " + ", ".join(item["name"] for item in failed) + ".")
        untested = [item["name"] for item in report["capabilities"] if item["status"] == "untested"]
        if untested:
            lines.append("Not recently verified: " + ", ".join(untested) + ".")
        lines.append(
            "Note: this checks local configuration and Ollama's model list; it does not execute every tool "
            "or prove that the configured model can generate a response."
        )
        return "\n".join(lines)
