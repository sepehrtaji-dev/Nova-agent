import time

import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel


def main():
    print("=" * 70)
    print("NOVA LARGE TRAINING BENCHMARK")
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

    batch_size = 1
    sequence_length = 512
    gradient_accumulation_steps = 8
    steps = 20

    print(f"Device: {device}")
    print(f"GPU: {torch.cuda.get_device_name(0)}")

    gpu_memory = (
        torch.cuda.get_device_properties(0).total_memory
        / 1024**3
    )

    print(f"GPU memory: {gpu_memory:.2f} GB")

    print()
    print("Building Nova Large...")

    model = NovaLanguageModel(config).to(device)

    parameters = sum(
        p.numel()
        for p in model.parameters()
    )

    print(f"Parameters: {parameters:,}")
    print(f"Sequence length: {sequence_length}")
    print(f"Batch size: {batch_size}")
    print(
        f"Gradient accumulation: "
        f"{gradient_accumulation_steps}"
    )
    print(
        f"Effective batch size: "
        f"{batch_size * gradient_accumulation_steps}"
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=3e-4,
        betas=(0.9, 0.95),
        weight_decay=0.1,
    )

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=True,
    )

    print()
    print("Starting benchmark...")
    print()

    model.train()

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()

    benchmark_start = time.perf_counter()

    total_tokens = 0
    total_loss = 0.0

    for step in range(1, steps + 1):
        step_start = time.perf_counter()

        optimizer.zero_grad(
            set_to_none=True
        )

        accumulated_loss = 0.0

        for _ in range(
            gradient_accumulation_steps
        ):
            input_ids = torch.randint(
                0,
                config.vocab_size,
                (
                    batch_size,
                    sequence_length,
                ),
                device=device,
                dtype=torch.long,
            )

            target_ids = torch.randint(
                0,
                config.vocab_size,
                (
                    batch_size,
                    sequence_length,
                ),
                device=device,
                dtype=torch.long,
            )

            with torch.autocast(
                device_type="cuda",
                dtype=torch.float16,
            ):
                _, loss = model(
                    input_ids,
                    target_ids,
                )

                scaled_loss = (
                    loss
                    / gradient_accumulation_steps
                )

            scaler.scale(
                scaled_loss
            ).backward()

            accumulated_loss += loss.item()
            total_tokens += (
                batch_size
                * sequence_length
            )

        scaler.unscale_(optimizer)

        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            1.0,
        )

        scaler.step(optimizer)
        scaler.update()

        average_loss = (
            accumulated_loss
            / gradient_accumulation_steps
        )

        total_loss += average_loss

        torch.cuda.synchronize()

        step_time = (
            time.perf_counter()
            - step_start
        )

        tokens_per_second = (
            batch_size
            * sequence_length
            * gradient_accumulation_steps
            / max(step_time, 1e-9)
        )

        peak_vram = (
            torch.cuda.max_memory_allocated()
            / 1024**3
        )

        print(
            f"Step {step:02d}/{steps} | "
            f"Loss: {average_loss:.4f} | "
            f"Tok/s: {tokens_per_second:.1f} | "
            f"Grad: {float(grad_norm):.3f} | "
            f"Peak VRAM: {peak_vram:.2f} GB"
        )

    torch.cuda.synchronize()

    total_time = (
        time.perf_counter()
        - benchmark_start
    )

    average_loss = (
        total_loss / steps
    )

    average_tokens_per_second = (
        total_tokens
        / max(total_time, 1e-9)
    )

    peak_vram = (
        torch.cuda.max_memory_allocated()
        / 1024**3
    )

    reserved_vram = (
        torch.cuda.max_memory_reserved()
        / 1024**3
    )

    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)

    print(
        f"Parameters:       {parameters:,}"
    )

    print(
        f"Average loss:     {average_loss:.4f}"
    )

    print(
        f"Total tokens:     {total_tokens:,}"
    )

    print(
        f"Total time:       {total_time:.2f}s"
    )

    print(
        f"Average Tok/s:    "
        f"{average_tokens_per_second:.1f}"
    )

    print(
        f"Peak VRAM:        "
        f"{peak_vram:.2f} GB"
    )

    print(
        f"Reserved VRAM:    "
        f"{reserved_vram:.2f} GB"
    )

    print()

    if peak_vram < gpu_memory * 0.90:
        print("STATUS: PASS")
        print(
            "Nova Large training benchmark "
            "fits within the VRAM safety target."
        )
    else:
        print("STATUS: WARNING")
        print(
            "VRAM usage is approaching the "
            "GPU limit."
        )

    print("=" * 70)


if __name__ == "__main__":
    main()