from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import Iterable


@dataclass
class TokenizerConfig:
    vocab_size: int = 32000
    min_frequency: int = 2
    max_unique_words: int = 200000


class ByteBPETokenizer:
    SPECIAL_TOKENS = {
        "<pad>": 0,
        "<unk>": 1,
        "<bos>": 2,
        "<eos>": 3,
    }

    BYTE_TOKEN_COUNT = 256

    def __init__(self, config: TokenizerConfig | None = None):
        self.config = config or TokenizerConfig()

        self.token_to_id = dict(self.SPECIAL_TOKENS)
        self.id_to_token = {
            token_id: token
            for token, token_id in self.token_to_id.items()
        }

        self.merges: dict[tuple[str, str], str] = {}
        self.merge_ranks: dict[tuple[str, str], int] = {}

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
        sequences: list[tuple[list[str], int]],
    ) -> Counter[tuple[str, str]]:
        counts: Counter[tuple[str, str]] = Counter()

        for sequence, frequency in sequences:
            if frequency <= 0:
                continue

            for i in range(len(sequence) - 1):
                counts[(sequence[i], sequence[i + 1])] += frequency

        return counts

    def _add_base_tokens(self) -> None:
        for byte in range(self.BYTE_TOKEN_COUNT):
            token = f"<0x{byte:02X}>"

            if token not in self.token_to_id:
                token_id = len(self.token_to_id)
                self.token_to_id[token] = token_id
                self.id_to_token[token_id] = token

    def train(
        self,
        texts: Iterable[str],
        max_unique_words: int | None = None,
    ) -> None:
        if texts is None:
            raise ValueError("Training data cannot be empty.")

        limit = (
            self.config.max_unique_words
            if max_unique_words is None
            else max_unique_words
        )

        if limit <= 0:
            raise ValueError("max_unique_words must be greater than 0.")

        word_frequencies: Counter[str] = Counter()

        for text in texts:
            if not isinstance(text, str):
                continue

            for word in self._split_words(text):
                if not word:
                    continue

                if word in word_frequencies:
                    word_frequencies[word] += 1
                elif len(word_frequencies) < limit:
                    word_frequencies[word] = 1

        if not word_frequencies:
            raise ValueError("No usable text was found.")

        self._add_base_tokens()

        sequences: list[tuple[list[str], int]] = [
            (self._word_to_symbols(word), frequency)
            for word, frequency in word_frequencies.items()
        ]

        del word_frequencies

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
            self.merge_ranks[pair] = len(self.merge_ranks)

            token_id = len(self.token_to_id)
            self.token_to_id[merged] = token_id
            self.id_to_token[token_id] = merged

            updated_sequences: list[tuple[list[str], int]] = []

            for sequence, word_frequency in sequences:
                new_sequence: list[str] = []
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

                updated_sequences.append((new_sequence, word_frequency))

            sequences = updated_sequences

        del sequences

    def _apply_merges(self, symbols: list[str]) -> list[str]:
        symbols = symbols[:]

        while len(symbols) > 1:
            best_pair = None
            best_order = None
            best_index = -1

            for i in range(len(symbols) - 1):
                pair = (symbols[i], symbols[i + 1])
                order = self.merge_ranks.get(pair)

                if order is None:
                    continue

                if best_order is None or order < best_order:
                    best_pair = pair
                    best_order = order
                    best_index = i

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

            byte_data.extend(self._token_to_bytes(token))

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
                "max_unique_words": self.config.max_unique_words,
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

        config_data = data["config"]

        if "max_unique_words" not in config_data:
            config_data["max_unique_words"] = 200000

        config = TokenizerConfig(**config_data)
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

        tokenizer.merge_ranks = {
            pair: rank
            for rank, pair in enumerate(tokenizer.merges)
        }

        return tokenizer