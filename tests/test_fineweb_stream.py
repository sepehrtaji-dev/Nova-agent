from datasets import load_dataset

dataset = load_dataset(
    "HuggingFaceFW/fineweb-edu",
    "sample-10BT",
    split="train",
    streaming=True,
)

print("Dataset ready.")

for i, sample in enumerate(dataset):
    print("Document:", i)
    print(sample["text"][:100])

    if i >= 4:
        break

print("Streaming test passed.")