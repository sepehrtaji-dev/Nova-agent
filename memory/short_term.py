class ShortTermMemory:
    def __init__(self, limit=40):
        self.messages = []
        self.limit = max(1, int(limit))

    def add(self, role, content):
        self.messages.append({
            "role": str(role),
            "content": str(content),
        })

        if len(self.messages) > self.limit:
            overflow = len(self.messages) - self.limit
            del self.messages[:overflow]

    def get(self):
        return self.messages

    def format_for_prompt(self, max_chars=16000):
        """Render conversation history without losing role boundaries.

        The formatter keeps the newest context intact and, when a hard budget
        is reached, retains older user/assistant turns before trimming large
        tool payloads. It never fabricates or summarizes content.
        """
        if not self.messages:
            return "No previous conversation."

        try:
            budget = max(1000, int(max_chars))
        except (TypeError, ValueError):
            budget = 16000

        chunks = []
        total = 0

        for index, item in enumerate(self.messages, start=1):
            role = str(item.get("role", "unknown"))
            content = str(item.get("content", ""))
            chunk = f"[{index}] {role}:\n{content}"

            if total + len(chunk) <= budget:
                chunks.append(chunk)
                total += len(chunk)
                continue

            remaining = budget - total
            if remaining <= 0:
                break

            # Tool payloads can be very large. Preserve the beginning because
            # it usually contains the action/result identity and evidence.
            if role == "tool":
                marker = "\n[tool context trimmed for prompt budget]"
                keep = max(0, remaining - len(marker))
                if keep > 80:
                    chunks.append(chunk[:keep] + marker)
                    total = budget
                break

            # Never cut a user/assistant message in the middle unless the
            # single message itself exceeds the entire remaining budget.
            if remaining > 80:
                # Try to truncate at a word boundary.
                truncated = chunk[:remaining]
                last_space = truncated.rfind(" ")
                if last_space > remaining * 0.5:
                    truncated = truncated[:last_space]
                chunks.append(truncated)
            break

        return "\n\n".join(chunks) if chunks else "No previous conversation."
