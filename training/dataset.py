from __future__ import annotations

import random
from pathlib import Path
from typing import Iterator, Sequence

import pyarrow.parquet as pq
import torch
from torch.utils.data import DataLoader, IterableDataset

from model.tokenizer import ByteBPETokenizer


REPO = "HuggingFaceFW/fineweb-edu"
DATASET_ROOT = f"hf://datasets/{REPO}/sample/10BT"
PARQUET_PATTERN = f"{DATASET_ROOT}/*.parquet"


def discover_parquet_files() -> list[str]:
    try:
        from huggingface_hub import HfFileSystem
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required to discover FineWeb-Edu parquet files."
        ) from exc

    fs = HfFileSystem()
    files = fs.glob(f"datasets/{REPO}/sample/10BT/*.parquet")

    if not files:
        raise RuntimeError("No FineWeb-Edu parquet files were found.")

    return sorted(f"hf://{path}" for path in files)


def split_parquet_files(
    files: Sequence[str],
    validation_fraction: float = 0.05,
    seed: int = 42,
) -> tuple[list[str], list[str]]:
    if not files:
        raise ValueError("files cannot be empty.")

    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between 0 and 1.")

    shuffled = list(files)
    random.Random(seed).shuffle(shuffled)

    validation_count = max(1, int(len(shuffled) * validation_fraction))

    if validation_count >= len(shuffled):
        validation_count = 1

    validation_files = sorted(shuffled[:validation_count])
    train_files = sorted(shuffled[validation_count:])

    if not train_files:
        raise RuntimeError("The split produced no training files.")

    return train_files, validation_files


class FineWebTokenDataset(IterableDataset):
    def __init__(
        self,
        tokenizer: ByteBPETokenizer,
        files: Sequence[str],
        sequence_length: int = 512,
        max_documents: int | None = None,
        max_tokens: int | None = None,
        shuffle_files: bool = True,
        seed: int = 42,
    ):
        super().__init__()

        if sequence_length < 1:
            raise ValueError("sequence_length must be positive.")

        self.tokenizer = tokenizer
        self.files = list(files)
        self.sequence_length = sequence_length
        self.max_documents = max_documents
        self.max_tokens = max_tokens
        self.shuffle_files = shuffle_files
        self.seed = seed
        self._epoch = 0

        if not self.files:
            raise ValueError("At least one parquet file is required.")

    def _get_files_for_epoch(self) -> list[str]:
        files = list(self.files)

        if self.shuffle_files:
            random.Random(self.seed + self._epoch).shuffle(files)

        return files

    def _stream_text(self) -> Iterator[str]:
        documents = 0

        for file_path in self._get_files_for_epoch():
            parquet_file = pq.ParquetFile(file_path)

            row_groups = list(range(parquet_file.num_row_groups))

            if self.shuffle_files:
                random.Random(
                    self.seed + self._epoch + hash(file_path) % 1_000_000
                ).shuffle(row_groups)

            for row_group_index in row_groups:
                table = parquet_file.read_row_group(
                    row_group_index,
                    columns=["text"],
                )

                texts = table.column("text").to_pylist()

                if self.shuffle_files:
                    random.Random(
                        self.seed
                        + self._epoch
                        + row_group_index
                        + len(file_path)
                    ).shuffle(texts)

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
        self._epoch += 1

        token_buffer: list[int] = []
        total_tokens = 0

        for text in self._stream_text():
            tokens = self.tokenizer.encode(text)

            if not tokens:
                continue

            if self.max_tokens is not None:
                remaining = self.max_tokens - total_tokens

                if remaining <= 0:
                    return

                tokens = tokens[:remaining]

            token_buffer.extend(tokens)

            while len(token_buffer) >= self.sequence_length + 1:
                sequence = token_buffer[: self.sequence_length + 1]

                token_buffer = token_buffer[self.sequence_length :]

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
    files: Sequence[str],
    sequence_length: int = 512,
    batch_size: int = 4,
    max_documents: int | None = None,
    max_tokens: int | None = None,
    shuffle_files: bool = True,
    seed: int = 42,
) -> DataLoader:
    tokenizer = ByteBPETokenizer.load(tokenizer_path)

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        files=files,
        sequence_length=sequence_length,
        max_documents=max_documents,
        max_tokens=max_tokens,
        shuffle_files=shuffle_files,
        seed=seed,
    )

    return DataLoader(
        dataset,
        batch_size=batch_size,
        num_workers=0,
    )


def create_train_val_dataloaders(
    tokenizer_path: str | Path,
    sequence_length: int = 512,
    batch_size: int = 4,
    train_max_documents: int | None = None,
    train_max_tokens: int | None = None,
    validation_max_documents: int | None = None,
    validation_max_tokens: int | None = None,
    validation_fraction: float = 0.05,
    seed: int = 42,
) -> tuple[DataLoader, DataLoader]:
    files = discover_parquet_files()

    train_files, validation_files = split_parquet_files(
        files=files,
        validation_fraction=validation_fraction,
        seed=seed,
    )

    train_loader = create_dataloader(
        tokenizer_path=tokenizer_path,
        files=train_files,
        sequence_length=sequence_length,
        batch_size=batch_size,
        max_documents=train_max_documents,
        max_tokens=train_max_tokens,
        shuffle_files=True,
        seed=seed,
    )

    validation_loader = create_dataloader(
        tokenizer_path=tokenizer_path,
        files=validation_files,
        sequence_length=sequence_length,
        batch_size=batch_size,
        max_documents=validation_max_documents,
        max_tokens=validation_max_tokens,
        shuffle_files=False,
        seed=seed,
    )

    return train_loader, validation_loader


if __name__ == "__main__":
    tokenizer_path = Path("data/tokenizer/nova_tokenizer.json")

    files = discover_parquet_files()
    train_files, validation_files = split_parquet_files(
        files=files,
        validation_fraction=0.05,
        seed=42,
    )

    print("=" * 60)
    print("FINEWEB-Edu DATASET")
    print("=" * 60)
    print(f"Total parquet files: {len(files)}")
    print(f"Training files:      {len(train_files)}")
    print(f"Validation files:    {len(validation_files)}")
    print()
    print("Validation files:")
    for file_path in validation_files:
        print(f"  {file_path}")
    print()

    tokenizer = ByteBPETokenizer.load(tokenizer_path)

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        files=train_files,
        sequence_length=128,
        max_documents=20,
        max_tokens=5000,
        shuffle_files=True,
        seed=42,
    )

    sample = next(iter(dataset))

    print(f"Input shape:  {tuple(sample['input_ids'].shape)}")
    print(f"Target shape: {tuple(sample['target_ids'].shape)}")
    print(f"Input dtype:  {sample['input_ids'].dtype}")
    print(f"Target dtype: {sample['target_ids'].dtype}")

    assert sample["input_ids"].shape == (128,)
    assert sample["target_ids"].shape == (128,)
    assert sample["input_ids"].dtype == torch.long
    assert sample["target_ids"].dtype == torch.long

    print()
    print("DATASET TEST PASSED")
