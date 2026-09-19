from pathlib import Path

from datasets import load_dataset

from model.tokenizer import ByteBPETokenizer, TokenizerConfig


DATASET_NAME = "HuggingFaceFW/fineweb-edu"
DATASET_CONFIG = "sample-10BT"
SPLIT = "train"

OUTPUT_DIR = Path("data/tokenizer")
OUTPUT_FILE = OUTPUT_DIR / "nova_tokenizer.json"

MAX_DOCUMENTS = 100_000
MAX_TEXT_BYTES = 2_000_000_000


def stream_text():
    dataset = load_dataset(
        DATASET_NAME,
        DATASET_CONFIG,
        split=SPLIT,
        streaming=True,
    )

    total_documents = 0
    total_bytes = 0

    for sample in dataset:
        text = sample.get("text")

        if not isinstance(text, str):
            continue

        text = text.strip()

        if len(text) < 100:
            continue

        text_bytes = len(text.encode("utf-8"))

        if total_bytes + text_bytes > MAX_TEXT_BYTES:
            break

        yield text

        total_documents += 1
        total_bytes += text_bytes

        if total_documents >= MAX_DOCUMENTS:
            break


def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    config = TokenizerConfig(
        vocab_size=32000,
        min_frequency=2,
    )

    tokenizer = ByteBPETokenizer(config)

    print("=" * 60)
    print("NOVA TOKENIZER TRAINING")
    print("=" * 60)

    print(f"Dataset: {DATASET_NAME}")
    print(f"Config: {DATASET_CONFIG}")
    print(f"Max documents: {MAX_DOCUMENTS}")
    print(f"Max raw text: {MAX_TEXT_BYTES / 1_000_000_000:.2f} GB")
    print()

    tokenizer.train(stream_text())

    tokenizer.save(str(OUTPUT_FILE))

    print()
    print(f"Tokenizer saved to: {OUTPUT_FILE}")
    print(f"Vocabulary size: {tokenizer.vocab_size}")


if __name__ == "__main__":
    main()