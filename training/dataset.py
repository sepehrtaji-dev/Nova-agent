from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pyarrow.parquet as pq
import torch
from torch.utils.data import IterableDataset, DataLoader

from model.tokenizer import ByteBPETokenizer


REPO = "HuggingFaceFW/fineweb-edu"
FILE = "sample/10BT/013_00000.parquet"

PARQUET_URL = f"hf://datasets/{REPO}/{FILE}"


class FineWebTokenDataset(IterableDataset):
    def __init__(
        self,
        tokenizer: ByteBPETokenizer,
        sequence_length: int = 512,
        max_documents: int | None = None,
        max_tokens: int | None = None,
    ):
        super().__init__()

        self.tokenizer = tokenizer
        self.sequence_length = sequence_length
        self.max_documents = max_documents
        self.max_tokens = max_tokens

    def _stream_text(self) -> Iterator[str]:
        parquet_file = pq.ParquetFile(PARQUET_URL)

        documents = 0

        for row_group_index in range(parquet_file.num_row_groups):
            table = parquet_file.read_row_group(
                row_group_index,
                columns=["text"],
            )

            texts = table.column("text").to_pylist()

            for text in texts:
                if not isinstance(text, str):
                    continue

                text = text.strip()

                if not text:
                    continue

                yield text

                documents += 1

                if (
                    self.max_documents is not None
                    and documents >= self.max_documents
                ):
                    return

    def __iter__(self):
        token_buffer: list[int] = []
        total_tokens = 0

        for text in self._stream_text():
            tokens = self.tokenizer.encode(text)

            if not tokens:
                continue

            token_buffer.extend(tokens)

            if self.max_tokens is not None:
                remaining = self.max_tokens - total_tokens

                if remaining <= 0:
                    break

                if len(token_buffer) > remaining:
                    token_buffer = token_buffer[:remaining]

            while len(token_buffer) >= self.sequence_length + 1:
                sequence = token_buffer[
                    : self.sequence_length + 1
                ]

                token_buffer = token_buffer[
                    self.sequence_length:
                ]

                input_ids = torch.tensor(
                    sequence[:-1],
                    dtype=torch.long,
                )

                target_ids = torch.tensor(
                    sequence[1:],
                    dtype=torch.long,
                )

                total_tokens += self.sequence_length

                yield {
                    "input_ids": input_ids,
                    "target_ids": target_ids,
                }

                if (
                    self.max_tokens is not None
                    and total_tokens >= self.max_tokens
                ):
                    return


def create_dataloader(
    tokenizer_path: str | Path,
    sequence_length: int = 512,
    batch_size: int = 4,
    max_documents: int | None = None,
    max_tokens: int | None = None,
) -> DataLoader:

    tokenizer = ByteBPETokenizer.load(tokenizer_path)

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=sequence_length,
        max_documents=max_documents,
        max_tokens=max_tokens,
    )

    return DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=0,
    )