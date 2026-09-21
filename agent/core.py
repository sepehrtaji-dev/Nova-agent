import re

import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer


class NovaCore:

    def __init__(
        self,
        checkpoint_path="data/checkpoints/best.pt",
        tokenizer_path="data/tokenizer/nova_tokenizer.json",
        device=None,
        max_context_tokens=512,
        max_new_tokens=128,
        temperature=0.7,
        top_k=40,
        top_p=0.9,
        repetition_penalty=1.12,
        no_repeat_ngram_size=3,
    ):
        self.device = device or (
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        self.max_context_tokens = max(
            int(max_context_tokens),
            16,
        )

        self.max_new_tokens = max(
            int(max_new_tokens),
            1,
        )

        self.temperature = max(
            float(temperature),
            0.05,
        )

        self.top_k = max(
            int(top_k),
            0,
        )

        self.top_p = min(
            max(float(top_p), 0.0),
            1.0,
        )

        self.repetition_penalty = max(
            float(repetition_penalty),
            1.0,
        )

        self.no_repeat_ngram_size = max(
            int(no_repeat_ngram_size),
            0,
        )

        self.pad_token_id = 0
        self.unk_token_id = 1
        self.bos_token_id = 2
        self.eos_token_id = 3

        self.tokenizer = ByteBPETokenizer.load(
            tokenizer_path
        )

        self.model = NovaLanguageModel(
            ModelConfig()
        )

        checkpoint = torch.load(
            checkpoint_path,
            map_location="cpu",
            weights_only=False,
        )

        if isinstance(checkpoint, dict):
            if "model_state_dict" in checkpoint:
                state_dict = checkpoint[
                    "model_state_dict"
                ]
            elif "model" in checkpoint:
                state_dict = checkpoint["model"]
            else:
                state_dict = checkpoint
        else:
            state_dict = checkpoint

        self.model.load_state_dict(
            state_dict
        )

        self.model.to(self.device)
        self.model.eval()

        self.conversation = []

    def clear_context(self):
        self.conversation.clear()

    def add_message(
        self,
        role,
        content,
    ):
        if role not in {
            "user",
            "assistant",
        }:
            raise ValueError(
                f"Unsupported role: {role}"
            )

        self.conversation.append(
            {
                "role": role,
                "content": str(content),
            }
        )

    def build_prompt(self):
        parts = []

        for message in self.conversation:
            role = message["role"]
            content = message["content"]

            if role == "user":
                parts.append(
                    f"User: {content}"
                )

            elif role == "assistant":
                parts.append(
                    f"Assistant: {content}"
                )

        parts.append("Assistant:")

        return "\n".join(parts)

    def _trim_context(
        self,
        token_ids,
    ):
        if len(token_ids) <= self.max_context_tokens:
            return token_ids

        return token_ids[
            -self.max_context_tokens:
        ]

    def _apply_repetition_penalty(
        self,
        logits,
        generated_ids,
    ):
        if (
            self.repetition_penalty <= 1.0
            or generated_ids.numel() == 0
        ):
            return logits

        logits = logits.clone()

        token_ids = torch.unique(
            generated_ids
        )

        token_ids = token_ids[
            (token_ids >= 0)
            & (token_ids < logits.numel())
        ]

        if token_ids.numel() == 0:
            return logits

        values = logits[token_ids]

        values = torch.where(
            values < 0,
            values * self.repetition_penalty,
            values / self.repetition_penalty,
        )

        logits[token_ids] = values

        return logits

    def _get_banned_tokens(
        self,
        generated_ids,
    ):
        n = self.no_repeat_ngram_size

        if n <= 0:
            return set()

        tokens = generated_ids.tolist()

        if len(tokens) < n:
            return set()

        if n == 1:
            return set(tokens)

        prefix = tuple(
            tokens[-(n - 1):]
        )

        banned = set()

        limit = len(tokens) - n + 1

        for i in range(limit):
            ngram = tuple(
                tokens[i:i + n]
            )

            if ngram[:-1] == prefix:
                banned.add(
                    ngram[-1]
                )

        return banned

    def _apply_no_repeat_ngram(
        self,
        logits,
        generated_ids,
    ):
        banned = self._get_banned_tokens(
            generated_ids
        )

        if not banned:
            return logits

        logits = logits.clone()

        for token_id in banned:
            if (
                0 <= token_id
                < logits.numel()
            ):
                logits[token_id] = (
                    float("-inf")
                )

        return logits

    def _filter_special_tokens(
        self,
        logits,
    ):
        logits = logits.clone()

        for token_id in (
            self.pad_token_id,
            self.bos_token_id,
        ):
            if (
                0 <= token_id
                < logits.numel()
            ):
                logits[token_id] = (
                    float("-inf")
                )

        return logits

    def _top_k_filter(
        self,
        logits,
    ):
        if (
            self.top_k <= 0
            or self.top_k >= logits.numel()
        ):
            return logits

        values, _ = torch.topk(
            logits,
            self.top_k,
        )

        threshold = values[-1]

        return torch.where(
            logits < threshold,
            torch.full_like(
                logits,
                float("-inf"),
            ),
            logits,
        )

    def _top_p_filter(
        self,
        logits,
    ):
        if self.top_p >= 1.0:
            return logits

        sorted_logits, sorted_indices = (
            torch.sort(
                logits,
                descending=True,
            )
        )

        sorted_probs = torch.softmax(
            sorted_logits,
            dim=-1,
        )

        cumulative_probs = torch.cumsum(
            sorted_probs,
            dim=-1,
        )

        remove = (
            cumulative_probs
            > self.top_p
        )

        remove[0] = False

        sorted_logits = (
            sorted_logits.masked_fill(
                remove,
                float("-inf"),
            )
        )

        filtered = torch.full_like(
            logits,
            float("-inf"),
        )

        filtered.scatter_(
            0,
            sorted_indices,
            sorted_logits,
        )

        return filtered

    def _prepare_logits(
        self,
        logits,
        generated_ids,
    ):
        logits = logits.float()

        logits = torch.nan_to_num(
            logits,
            nan=float("-inf"),
            posinf=1e4,
            neginf=-1e4,
        )

        logits = self._filter_special_tokens(
            logits
        )

        logits = self._apply_repetition_penalty(
            logits,
            generated_ids,
        )

        logits = self._apply_no_repeat_ngram(
            logits,
            generated_ids,
        )

        logits = logits / self.temperature

        logits = self._top_k_filter(
            logits
        )

        logits = self._top_p_filter(
            logits
        )

        return logits

    def _select_next_token(
        self,
        logits,
        generated_ids,
    ):
        logits = self._prepare_logits(
            logits,
            generated_ids,
        )

        if not torch.isfinite(
            logits
        ).any():
            return torch.tensor(
                self.eos_token_id,
                dtype=torch.long,
                device=logits.device,
            )

        probabilities = torch.softmax(
            logits,
            dim=-1,
        )

        if (
            not torch.isfinite(
                probabilities
            ).all()
            or probabilities.sum() <= 0
        ):
            return torch.argmax(
                logits
            )

        probabilities = probabilities / (
            probabilities.sum()
        )

        return torch.multinomial(
            probabilities,
            1,
        ).squeeze(0)

    def _clean_output(
        self,
        text,
    ):
        if not text:
            return ""

        for token in (
            "<eos>",
            "<bos>",
            "<pad>",
        ):
            text = text.replace(
                token,
                "",
            )

        text = re.sub(
            r"(?:<eos>)+",
            "",
            text,
        )

        text = re.sub(
            r"(?:eos>)+",
            "",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    @torch.inference_mode()
    def generate(
        self,
        prompt,
    ):
        token_ids = self.tokenizer.encode(
            prompt
        )

        if not token_ids:
            return ""

        token_ids = self._trim_context(
            token_ids
        )

        generated = torch.tensor(
            token_ids,
            dtype=torch.long,
            device=self.device,
        )

        prompt_length = generated.numel()

        generated_new_tokens = 0

        for _ in range(
            self.max_new_tokens
        ):
            context = generated[
                -self.max_context_tokens:
            ].unsqueeze(0)

            logits, _ = self.model(
                input_ids=context
            )

            next_logits = logits[
                0,
                -1,
            ]

            next_token = (
                self._select_next_token(
                    next_logits,
                    generated,
                )
            )

            next_token_id = int(
                next_token.item()
            )

            if next_token_id == self.eos_token_id:
                break

            if next_token_id == self.pad_token_id:
                break

            if next_token_id == self.bos_token_id:
                break

            generated = torch.cat(
                (
                    generated,
                    next_token.view(1),
                ),
                dim=0,
            )

            generated_new_tokens += 1

            if generated_new_tokens >= (
                self.max_new_tokens
            ):
                break

        if generated.numel() <= prompt_length:
            return ""

        output_ids = generated[
            prompt_length:
        ].tolist()

        output = self.tokenizer.decode(
            output_ids
        )

        return self._clean_output(
            output
        )

    def chat(
        self,
        user_message,
    ):
        user_message = str(
            user_message
        ).strip()

        if not user_message:
            return ""

        self.add_message(
            "user",
            user_message,
        )

        prompt = self.build_prompt()

        response = self.generate(
            prompt
        )

        self.add_message(
            "assistant",
            response,
        )

        return response