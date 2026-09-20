import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer
from training.dataset import FineWebTokenDataset


TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"


def main():
    print("=" * 60)
    print("NOVA TRAINING STEP TEST")
    print("=" * 60)

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    print()
    print("Device:", device)

    if device.type == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

    print()
    print("Loading tokenizer...")

    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    config = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        max_sequence_length=128,
        embedding_dim=256,
        num_layers=6,
        num_heads=8,
        feed_forward_dim=1024,
        dropout=0.1,
    )

    print("Vocabulary size:", config.vocab_size)
    print("Sequence length:", config.max_sequence_length)
    print("Embedding dim:", config.embedding_dim)
    print("Layers:", config.num_layers)
    print("Heads:", config.num_heads)

    print()
    print("Creating model...")

    model = NovaLanguageModel(config).to(device)

    parameter_count = sum(
        parameter.numel()
        for parameter in model.parameters()
    )

    print(
        f"Parameters: {parameter_count:,}"
    )

    print()
    print("Loading one FineWeb batch...")

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=config.max_sequence_length,
        max_documents=100,
        max_tokens=2_000,
    )

    sample = next(iter(dataset))

    input_ids = sample["input_ids"].unsqueeze(0).to(device)
    target_ids = sample["target_ids"].unsqueeze(0).to(device)

    print("Input shape :", tuple(input_ids.shape))
    print("Target shape:", tuple(target_ids.shape))

    print()
    print("Running forward pass...")

    model.train()

    logits, loss = model(
        input_ids,
        targets=target_ids,
    )

    print("Logits shape:", tuple(logits.shape))
    print("Loss:", loss.item())

    print()
    print("Running backward pass...")

    loss.backward()

    gradient_count = 0
    gradient_norm = 0.0

    for parameter in model.parameters():
        if parameter.grad is not None:
            gradient_count += 1
            gradient_norm += parameter.grad.detach().norm().item() ** 2

    gradient_norm = gradient_norm ** 0.5

    print("Parameters with gradients:", gradient_count)
    print("Gradient norm:", gradient_norm)

    assert logits.shape == (
        1,
        config.max_sequence_length,
        config.vocab_size,
    )

    assert torch.isfinite(loss)

    assert gradient_count > 0

    assert gradient_norm > 0

    print()
    print("=" * 60)
    print("TRAINING STEP TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()