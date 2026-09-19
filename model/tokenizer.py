from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import re


@dataclass
class TokenizerConfig:
    vocab_size: int = 32000
    min_frequency: int = 2


class ByteBPETokenizer:
    SPECIAL_TOKENS = {
        "<pad>": 0,
        "<unk>": 1,
        "<bos>": 2,
        "<eos>": 3,
    }

    def __init__(self, config: TokenizerConfig | None = None):
        self.config = config or TokenizerConfig()

        self.token_to_id = dict(self.SPECIAL_TOKENS)
        self.id_to_token = {
            token_id: token
            for token, token_id in self.token_to_id.items()
        }

        self.merges: dict[tuple[str, str], str] = {}

    @property
    def vocab_size(self) -> int:
        return len(self.token_to_id)

    def _split_words(self, text: str) -> list[str]:
        return re.findall(r"\S+|\s+", text, re.UNICODE)

    def _word_to_symbols(self, word: str) -> list[str]:
        data = word.encode("utf-8")
        return [f"<0x{byte:02X}>" for byte in data]

    def _pair_counts(
        self,
        sequences: list[list[str]],
    ) -> Counter[tuple[str, str]]:
        counts = Counter()

        for sequence in sequences:
            for i in range(len(sequence) - 1):
                counts[(sequence[i], sequence[i + 1])] += 1

        return counts

    def train(self, texts: list[str]) -> None:
        if not texts:
            raise ValueError("Training data cannot be empty.")

        sequences = []

        for text in texts:
            for word in self._split_words(text):
                if word:
                    sequences.append(self._word_to_symbols(word))

        if not sequences:
            raise ValueError("No usable text was found.")

        for byte in range(256):
            token = f"<0x{byte:02X}>"

            if token not in self.token_to_id:
                token_id = len(self.token_to_id)
                self.token_to_id[token] = token_id
                self.id_to_token[token_id] = token

        while len(self.token_to_id) < self.config.vocab_size:
            pair_counts = self._pair_counts(sequences)

            if not pair_counts:
                break

            pair, frequency = pair_counts.most_common(1)[0]

            if frequency < self.config.min_frequency:
                break

            merged = pair[0] + pair[1]

            if merged in self.token_to_id:
                break

            self.merges[pair] = merged

            token_id = len(self.token_to_id)
            self.token_to_id[merged] = token_id
            self.id_to_token[token_id] = merged

            new_sequences = []

            for sequence in sequences:
                new_sequence = []
                i = 0

                while i < len(sequence):
                    if (
                        i < len(sequence) - 1
                        and (sequence[i], sequence[i + 1]) == pair
                    ):
                        new_sequence.append(merged)
                        i += 2
                    else:
                        new_sequence.append(sequence[i])
                        i += 1

                new_sequences.append(new_sequence)

            sequences = new_sequences

    def _apply_merges(self, symbols: list[str]) -> list[str]:
        symbols = symbols[:]

        while True:
            best_pair = None
            best_order = None

            for pair in self.merges:
                try:
                    index = next(
                        i
                        for i in range(len(symbols) - 1)
                        if (symbols[i], symbols[i + 1]) == pair
                    )
                except StopIteration:
                    continue

                order = list(self.merges).index(pair)

                if best_order is None or order < best_order:
                    best_pair = pair
                    best_order = order
                    best_index = index

            if best_pair is None:
                break

            merged = self.merges[best_pair]

            symbols = (
                symbols[:best_index]
                + [merged]
                + symbols[best_index + 2:]
            )

        return symbols

    def encode(
        self,
        text: str,
        add_bos: bool = False,
        add_eos: bool = False,
    ) -> list[int]:
        tokens = []

        if add_bos:
            tokens.append(self.SPECIAL_TOKENS["<bos>"])

        for word in self._split_words(text):
            symbols = self._word_to_symbols(word)
            symbols = self._apply_merges(symbols)

            for symbol in symbols:
                token_id = self.token_to_id.get(
                    symbol,
                    self.SPECIAL_TOKENS["<unk>"],
                )
                tokens.append(token_id)

        if add_eos:
            tokens.append(self.SPECIAL_TOKENS["<eos>"])

        return tokens

    def decode(self, token_ids: list[int]) -> str:
        byte_data = bytearray()

        for token_id in token_ids:
            token = self.id_to_token.get(token_id)

            if token is None:
                continue

            if token in self.SPECIAL_TOKENS:
                continue

            if token.startswith("<0x") and token.endswith(">"):
                try:
                    byte_data.append(int(token[3:-1], 16))
                except ValueError:
                    continue
            else:
                for byte in self._token_to_bytes(token):
                    byte_data.extend(byte)

        return byte_data.decode("utf-8", errors="replace")

    def _token_to_bytes(self, token: str) -> bytes:
        result = bytearray()

        for match in re.finditer(r"<0x([0-9A-F]{2})>", token):
            result.append(int(match.group(1), 16))

        return bytes(result)

    def save(self, path: str | Path) -> None:
        path = Path(path)

        data = {
            "config": {
                "vocab_size": self.config.vocab_size,
                "min_frequency": self.config.min_frequency,
            },
            "token_to_id": self.token_to_id,
            "merges": [
                {
                    "left": left,
                    "right": right,
                    "merged": merged,
                }
                for (left, right), merged in self.merges.items()
            ],
        }

        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(cls, path: str | Path) -> "ByteBPETokenizer":
        path = Path(path)

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        config = TokenizerConfig(**data["config"])
        tokenizer = cls(config)

        tokenizer.token_to_id = {
            token: int(token_id)
            for token, token_id in data["token_to_id"].items()
        }

        tokenizer.id_to_token = {
            token_id: token
            for token, token_id in tokenizer.token_to_id.items()
        }

        tokenizer.merges = {
            (item["left"], item["right"]): item["merged"]
            for item in data["merges"]
        }

        return tokenizer