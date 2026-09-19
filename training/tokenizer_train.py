from pathlib import Path
import sys
import time

import pyarrow.parquet as pq


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from model.tokenizer import ByteBPETokenizer, TokenizerConfig


REPO = "HuggingFaceFW/fineweb-edu"
FILE = "sample/10BT/013_00000.parquet"

PARQUET_URL = f"hf://datasets/{REPO}/{FILE}"

OUTPUT_DIR = PROJECT_ROOT / "data" / "tokenizer"
OUTPUT_FILE = OUTPUT_DIR / "nova_tokenizer.json"

MAX_DOCUMENTS = 100_000
MAX_TEXT_BYTES = 500 * 1024 * 1024
MAX_UNIQUE_WORDS = 200_000

VOCAB_SIZE = 32_000
MIN_FREQUENCY = 2

ROW_GROUP_SIZE = 1


def stream_text():
    parquet = pq.ParquetFile(PARQUET_URL)

    total_documents = 0
    total_bytes = 0

    for row_group in range(parquet.num_row_groups):
        if total_documents >= MAX_DOCUMENTS:
            print("\nReached maximum documents.")
            return

        table = parquet.read_row_group(
            row_group,
            columns=["text"],
        )

        for value in table["text"]:
            if total_documents >= MAX_DOCUMENTS:
                print("\nReached maximum documents.")
                return

            text = value.as_py()

            if not isinstance(text, str):
                continue

            text = text.strip()

            if len(text) < 100:
                continue

            text_bytes = len(text.encode("utf-8"))

            if total_bytes + text_bytes > MAX_TEXT_BYTES:
                print("\nReached maximum data size.")
                return

            total_documents += 1
            total_bytes += text_bytes

            if total_documents % 1000 == 0:
                mb = total_bytes / (1024 * 1024)

                print(
                    f"\rDocuments: {total_documents:,} | "
                    f"Data: {mb:.1f} MB",
                    end="",
                    flush=True,
                )

            yield text

        del table

    print("\nDataset exhausted.")


def main():
    print("=" * 60)
    print("NOVA TOKENIZER TRAINING")
    print("=" * 60)
    print()

    print(f"Dataset: {REPO}")
    print(f"Parquet: {FILE}")
    print(f"Maximum documents: {MAX_DOCUMENTS:,}")
    print(
        f"Maximum text size: "
        f"{MAX_TEXT_BYTES / (1024 * 1024):.0f} MB"
    )
    print(f"Maximum unique words: {MAX_UNIQUE_WORDS:,}")
    print(f"Vocabulary size: {VOCAB_SIZE:,}")
    print()

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    tokenizer = ByteBPETokenizer(
        TokenizerConfig(
            vocab_size=VOCAB_SIZE,
            min_frequency=MIN_FREQUENCY,
            max_unique_words=MAX_UNIQUE_WORDS,
        )
    )

    print("Opening Parquet dataset...")
    print()

    start_time = time.time()

    tokenizer.train(
        stream_text(),
        max_unique_words=MAX_UNIQUE_WORDS,
    )

    elapsed = time.time() - start_time

    tokenizer.save(OUTPUT_FILE)

    print()
    print("=" * 60)
    print("TOKENIZER TRAINING COMPLETE")
    print("=" * 60)
    print()
    print(f"Vocabulary: {tokenizer.vocab_size:,}")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Time: {elapsed / 60:.2f} minutes")
    print()


if __name__ == "__main__":
    main()