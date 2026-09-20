from __future__ import annotations

import math
import random
import time
from pathlib import Path

import torch
from torch import nn

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer
from training.dataset import FineWebTokenDataset


TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"
CHECKPOINT_DIR = Path("data/checkpoints")


def set_seed(seed: int = 42):
    random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    scaler: torch.amp.GradScaler,
    step: int,
    loss: float,
):
    path.parent.mkdir(parents=True, exist_ok=True)

    torch.save(
        {
            "step": step,
            "loss": loss,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scaler_state_dict": scaler.state_dict(),
        },
        path,
    )


def train(
    max_steps: int = 20,
    sequence_length: int = 128,
    batch_size: int = 4,
    learning_rate: float = 3e-4,
    gradient_accumulation_steps: int = 1,
    max_documents: int = 1_000,
    max_tokens: int = 100_000,
    seed: int = 42,
):
    set_seed(seed)

    device = torch.device(
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    print("=" * 60)
    print("NOVA TRAINER")
    print("=" * 60)

    print()
    print("Device:", device)

    if device.type == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    config = ModelConfig(
        vocab_size=tokenizer.vocab_size,
        max_sequence_length=sequence_length,
        embedding_dim=256,
        num_layers=6,
        num_heads=8,
        feed_forward_dim=1024,
        dropout=0.1,
    )

    model = NovaLanguageModel(config).to(device)

    parameter_count = sum(
        parameter.numel()
        for parameter in model.parameters()
    )

    print(f"Parameters: {parameter_count:,}")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.1,
    )

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=device.type == "cuda",
    )

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=sequence_length,
        max_documents=max_documents,
        max_tokens=max_tokens,
    )

    data_iterator = iter(dataset)

    model.train()

    optimizer.zero_grad(set_to_none=True)

    running_loss = 0.0
    start_time = time.perf_counter()

    print()
    print("Starting training...")
    print()

    for step in range(1, max_steps + 1):
        step_loss = 0.0

        for _ in range(gradient_accumulation_steps):
            batch_inputs = []
            batch_targets = []

            for _ in range(batch_size):
                try:
                    sample = next(data_iterator)
                except StopIteration:
                    data_iterator = iter(dataset)
                    sample = next(data_iterator)

                batch_inputs.append(sample["input_ids"])
                batch_targets.append(sample["target_ids"])

            input_ids = torch.stack(batch_inputs).to(
                device,
                non_blocking=True,
            )

            target_ids = torch.stack(batch_targets).to(
                device,
                non_blocking=True,
            )

            with torch.autocast(
                device_type=device.type,
                dtype=torch.float16,
                enabled=device.type == "cuda",
            ):
                _, loss = model(
                    input_ids,
                    targets=target_ids,
                )

                scaled_loss = loss / gradient_accumulation_steps

            scaler.scale(scaled_loss).backward()

            step_loss += loss.detach().item()

        scaler.unscale_(optimizer)

        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            max_norm=1.0,
        )

        scaler.step(optimizer)
        scaler.update()

        optimizer.zero_grad(set_to_none=True)

        running_loss += step_loss / gradient_accumulation_steps

        elapsed = time.perf_counter() - start_time

        tokens_processed = (
            step
            * batch_size
            * sequence_length
            * gradient_accumulation_steps
        )

        tokens_per_second = (
            tokens_processed / elapsed
            if elapsed > 0
            else 0.0
        )

        perplexity = math.exp(
            min(step_loss / gradient_accumulation_steps, 20)
        )

        print(
            f"Step {step:04d}/{max_steps} | "
            f"Loss: {step_loss / gradient_accumulation_steps:.4f} | "
            f"PPL: {perplexity:.2f} | "
            f"Tokens/s: {tokens_per_second:.1f}"
        )

        if step % 10 == 0 or step == max_steps:
            checkpoint_path = (
                CHECKPOINT_DIR / f"checkpoint_step_{step}.pt"
            )

            save_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                scaler,
                step,
                step_loss / gradient_accumulation_steps,
            )

            print(
                f"Checkpoint saved: {checkpoint_path}"
            )

    print()
    print("=" * 60)
    print("TRAINING FINISHED")
    print("=" * 60)

    print(
        f"Average loss: "
        f"{running_loss / max_steps:.4f}"
    )


if __name__ == "__main__":
    train()