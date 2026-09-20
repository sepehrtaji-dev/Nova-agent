from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush
from pathlib import Path
from typing import Iterable
import json
import re


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

    def _add_byte_tokens(self) -> None:
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
        max_unique_words = (
            max_unique_words
            if max_unique_words is not None
            else self.config.max_unique_words
        )

        print()
        print("=" * 60)
        print("TOKENIZER TRAINING")
        print("=" * 60)
        print()
        print("Stage 1/3: collecting word statistics...")

        word_counts: Counter[str] = Counter()
        documents = 0
        total_words = 0

        for text in texts:
            if not isinstance(text, str):
                continue

            documents += 1

            for word in self._split_words(text):
                if not word:
                    continue

                total_words += 1

                if word in word_counts:
                    word_counts[word] += 1
                    continue

                if len(word_counts) < max_unique_words:
                    word_counts[word] = 1

            if documents % 1000 == 0:
                print(
                    f"\rDocuments processed: {documents:,} | "
                    f"Unique words: {len(word_counts):,}",
                    end="",
                    flush=True,
                )

        print()

        if not word_counts:
            raise ValueError("No usable text was found.")

        print()
        print(f"Documents processed: {documents:,}")
        print(f"Total words: {total_words:,}")
        print(f"Unique words: {len(word_counts):,}")

        self._add_byte_tokens()

        print()
        print("Stage 2/3: building BPE statistics...")

        words = list(word_counts.keys())
        frequencies = [word_counts[word] for word in words]

        sequences = [
            self._word_to_symbols(word)
            for word in words
        ]

        pair_counts: Counter[tuple[str, str]] = Counter()
        pair_words: dict[tuple[str, str], set[int]] = defaultdict(set)

        for word_id, sequence in enumerate(sequences):
            frequency = frequencies[word_id]

            for i in range(len(sequence) - 1):
                pair = (sequence[i], sequence[i + 1])
                pair_counts[pair] += frequency
                pair_words[pair].add(word_id)

            if word_id % 10000 == 0:
                print(
                    f"\rWords indexed: {word_id:,} / {len(words):,}",
                    end="",
                    flush=True,
                )

        print()
        print(f"Unique pairs: {len(pair_counts):,}")

        print()
        print("Stage 3/3: training BPE merges...")

        heap = []
        heap_order = 0

        for pair, count in pair_counts.items():
            heappush(
                heap,
                (-count, heap_order, pair),
            )
            heap_order += 1

        target_merges = max(
            0,
            self.config.vocab_size - self.vocab_size,
        )

        print(f"Target merges: {target_merges:,}")
        print()

        for merge_index in range(target_merges):
            pair = None

            while heap:
                negative_count, _, candidate = heappop(heap)
                current_count = pair_counts.get(candidate, 0)

                if current_count <= 0:
                    continue

                if -negative_count != current_count:
                    heappush(
                        heap,
                        (-current_count, heap_order, candidate),
                    )
                    heap_order += 1
                    continue

                pair = candidate
                break

            if pair is None:
                print("No more valid pairs.")
                break

            frequency = pair_counts[pair]

            if frequency < self.config.min_frequency:
                print(
                    f"Stopping: best pair frequency "
                    f"{frequency} < minimum {self.config.min_frequency}."
                )
                break

            left, right = pair
            merged = left + right

            if merged in self.token_to_id:
                pair_counts[pair] = 0
                continue

            self.merges[pair] = merged
            self.merge_ranks[pair] = len(self.merges)

            token_id = len(self.token_to_id)

            self.token_to_id[merged] = token_id
            self.id_to_token[token_id] = merged

            affected_words = list(
                pair_words.get(pair, ())
            )

            for word_id in affected_words:
                sequence = sequences[word_id]
                word_frequency = frequencies[word_id]

                old_pairs = []

                for i in range(len(sequence) - 1):
                    old_pairs.append(
                        (sequence[i], sequence[i + 1])
                    )

                i = 0
                new_sequence = []

                while i < len(sequence):
                    if (
                        i < len(sequence) - 1
                        and sequence[i] == left
                        and sequence[i + 1] == right
                    ):
                        new_sequence.append(merged)
                        i += 2
                    else:
                        new_sequence.append(sequence[i])
                        i += 1

                sequences[word_id] = new_sequence

                new_pairs = []

                for i in range(len(new_sequence) - 1):
                    new_pairs.append(
                        (
                            new_sequence[i],
                            new_sequence[i + 1],
                        )
                    )

                for old_pair in old_pairs:
                    pair_counts[old_pair] -= word_frequency

                    if pair_counts[old_pair] <= 0:
                        pair_counts.pop(old_pair, None)
                        pair_words.pop(old_pair, None)

                    else:
                        heappush(
                            heap,
                            (
                                -pair_counts[old_pair],
                                heap_order,
                                old_pair,
                            ),
                        )
                        heap_order += 1

                    ids = pair_words.get(old_pair)

                    if ids is not None:
                        ids.discard(word_id)

                        if not ids:
                            pair_words.pop(old_pair, None)

                for new_pair in new_pairs:
                    pair_counts[new_pair] += word_frequency
                    pair_words[new_pair].add(word_id)

                    heappush(
                        heap,
                        (
                            -pair_counts[new_pair],
                            heap_order,
                            new_pair,
                        ),
                    )
                    heap_order += 1

            pair_counts.pop(pair, None)
            pair_words.pop(pair, None)

            completed = merge_index + 1

            if (
                completed <= 10
                or completed % 100 == 0
                or completed == target_merges
            ):
                print(
                    f"Merge {completed:,} / "
                    f"{target_merges:,} | "
                    f"Pair frequency: {frequency:,} | "
                    f"Vocabulary: {self.vocab_size:,}",
                    flush=True,
                )

        print()
        print("Tokenizer training finished.")
        print(f"Final vocabulary: {self.vocab_size:,}")
        print(f"Total merges: {len(self.merges):,}")

    def _apply_merges(
        self,
        symbols: list[str],
    ) -> list[str]:
        symbols = symbols[:]

        while len(symbols) > 1:
            best_pair = None
            best_rank = None
            best_index = None

            for i in range(len(symbols) - 1):
                pair = (
                    symbols[i],
                    symbols[i + 1],
                )

                rank = self.merge_ranks.get(pair)

                if rank is None:
                    continue

                if best_rank is None or rank < best_rank:
                    best_pair = pair
                    best_rank = rank
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
            tokens.append(
                self.SPECIAL_TOKENS["<bos>"]
            )

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
            tokens.append(
                self.SPECIAL_TOKENS["<eos>"]
            )

        return tokens

    def decode(self, token_ids: list[int]) -> str:
        byte_data = bytearray()

        for token_id in token_ids:
            token = self.id_to_token.get(token_id)

            if token is None:
                continue

            if token in self.SPECIAL_TOKENS:
                continue

            byte_data.extend(
                self._token_to_bytes(token)
            )

        return byte_data.decode(
            "utf-8",
            errors="replace",
        )

    def _token_to_bytes(self, token: str) -> bytes:
        result = bytearray()

        for match in re.finditer(
            r"<0x([0-9A-F]{2})>",
            token,
        ):
            result.append(
                int(match.group(1), 16)
            )

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

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    @classmethod
    def load(
        cls,
        path: str | Path,
    ) -> "ByteBPETokenizer":
        path = Path(path)

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        config_data = data["config"]

        if "max_unique_words" not in config_data:
            config_data["max_unique_words"] = 200000

        config = TokenizerConfig(**config_data)

        tokenizer = cls(config)

        tokenizer.token_to_id = {
            token: int(token_id)
            for token, token_id
            in data["token_to_id"].items()
        }

        tokenizer.id_to_token = {
            token_id: token
            for token_id, token
            in tokenizer.token_to_id.items()
        }

        tokenizer.merges = {
            (
                item["left"],
                item["right"],
            ): item["merged"]
            for item in data["merges"]
        }

        tokenizer.merge_ranks = {
            pair: rank
            for rank, pair
            in enumerate(tokenizer.merges)
        }

        return tokenizer