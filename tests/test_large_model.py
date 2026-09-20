import time

import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel


def main():
    print("=" * 70)
    print("NOVA LARGE MODEL TEST")
    print("=" * 70)

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available.")

    device = torch.device("cuda")

    config = ModelConfig(
        vocab_size=32000,
        max_sequence_length=512,
        embedding_dim=1024,
        num_layers=22,
        num_heads=16,
        feed_forward_dim=4096,
        dropout=0.1,
    )

    print(f"Device: {device}")
    print(f"GPU: {torch.cuda.get_device_name(0)}")

    total_memory = (
        torch.cuda.get_device_properties(0).total_memory
        / 1024**3
    )

    print(f"GPU memory: {total_memory:.2f} GB")

    print()
    print("Building model...")

    model = NovaLanguageModel(config).to(device)

    parameters = sum(
        parameter.numel()
        for parameter in model.parameters()
    )

    trainable_parameters = sum(
        parameter.numel()
        for parameter in model.parameters()
        if parameter.requires_grad
    )

    print(f"Parameters: {parameters:,}")
    print(f"Trainable parameters: {trainable_parameters:,}")

    print()
    print("Running forward pass...")

    batch_size = 1
    sequence_length = 256

    input_ids = torch.randint(
        0,
        config.vocab_size,
        (batch_size, sequence_length),
        device=device,
        dtype=torch.long,
    )

    target_ids = torch.randint(
        0,
        config.vocab_size,
        (batch_size, sequence_length),
        device=device,
        dtype=torch.long,
    )

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    start = time.perf_counter()

    with torch.autocast(
        device_type="cuda",
        dtype=torch.float16,
    ):
        logits, loss = model(
            input_ids,
            target_ids,
        )

    torch.cuda.synchronize()

    forward_time = (
        time.perf_counter() - start
    )

    print(f"Logits shape: {tuple(logits.shape)}")
    print(f"Loss: {loss.item():.6f}")
    print(f"Forward time: {forward_time:.3f}s")

    allocated = (
        torch.cuda.memory_allocated()
        / 1024**3
    )

    reserved = (
        torch.cuda.memory_reserved()
        / 1024**3
    )

    peak = (
        torch.cuda.max_memory_allocated()
        / 1024**3
    )

    print()
    print("VRAM after forward:")
    print(f"Allocated: {allocated:.2f} GB")
    print(f"Reserved:  {reserved:.2f} GB")
    print(f"Peak:     {peak:.2f} GB")

    print()
    print("Running backward pass...")

    torch.cuda.reset_peak_memory_stats()

    model.zero_grad(
        set_to_none=True
    )

    start = time.perf_counter()

    with torch.autocast(
        device_type="cuda",
        dtype=torch.float16,
    ):
        logits, loss = model(
            input_ids,
            target_ids,
        )

    scaler = torch.amp.GradScaler(
        "cuda"
    )

    scaler.scale(loss).backward()

    torch.cuda.synchronize()

    backward_time = (
        time.perf_counter() - start
    )

    peak_backward = (
        torch.cuda.max_memory_allocated()
        / 1024**3
    )

    print(f"Backward time: {backward_time:.3f}s")
    print(
        f"Peak VRAM during backward: "
        f"{peak_backward:.2f} GB"
    )

    print()
    print("=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)

    print(f"Parameters: {parameters:,}")
    print(f"Forward:   {forward_time:.3f}s")
    print(f"Backward:  {backward_time:.3f}s")
    print(
        f"Peak VRAM: {peak_backward:.2f} GB"
    )

    if peak_backward < total_memory * 0.90:
        print("STATUS: PASS")
        print("Nova Large fits within the VRAM safety target.")
    else:
        print("STATUS: WARNING")
        print("VRAM usage is getting close to the GPU limit.")


if __name__ == "__main__":
    main()