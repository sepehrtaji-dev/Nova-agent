from pathlib import Path

from model.tokenizer import ByteBPETokenizer
from training.instruction_dataset import (
    InstructionDataset,
    instruction_collate_fn,
)


TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"
DATASET_PATH = "data/instruction/nova_instructions.jsonl"


def main():
    print("=" * 70)
    print("NOVA INSTRUCTION DATASET TEST")
    print("=" * 70)

    print(f"Tokenizer: {TOKENIZER_PATH}")
    print(f"Dataset:   {DATASET_PATH}")

    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    dataset = InstructionDataset(
        data_path=DATASET_PATH,
        tokenizer=tokenizer,
        max_sequence_length=512,
    )

    print(f"Samples: {len(dataset)}")

    sample = dataset[0]

    print()
    print("First sample:")
    print("Input shape:", tuple(sample["input_ids"].shape))
    print("Labels shape:", tuple(sample["labels"].shape))
    print("Attention shape:", tuple(sample["attention_mask"].shape))

    print()
    print("Input IDs:")
    print(sample["input_ids"][:30].tolist())

    print()
    print("Labels:")
    print(sample["labels"][:30].tolist())

    batch = instruction_collate_fn(
        [dataset[0], dataset[1], dataset[2]]
    )

    print()
    print("Batch:")
    print("Input shape:", tuple(batch["input_ids"].shape))
    print("Labels shape:", tuple(batch["labels"].shape))
    print("Attention shape:", tuple(batch["attention_mask"].shape))

    ignored = (batch["labels"] == -100).sum().item()
    trainable = (batch["labels"] != -100).sum().item()

    print()
    print("Ignored prompt/padding tokens:", ignored)
    print("Trainable response tokens:", trainable)

    if trainable <= 0:
        raise RuntimeError(
            "No trainable response tokens found."
        )

    print()
    print("=" * 70)
    print("INSTRUCTION DATASET TEST PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()