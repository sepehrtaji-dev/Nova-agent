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
    scheduler,
    scaler,
    step: int,
    train_loss: float,
    best_val_loss: float,
):
    path.parent.mkdir(parents=True, exist_ok=True)

    torch.save(
        {
            "step": step,
            "train_loss": train_loss,
            "best_val_loss": best_val_loss,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "scaler_state_dict": scaler.state_dict(),
        },
        path,
    )


def load_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    scheduler,
    scaler,
    device: torch.device,
):
    checkpoint = torch.load(
        path,
        map_location=device,
    )

    model.load_state_dict(
        checkpoint["model_state_dict"]
    )

    optimizer.load_state_dict(
        checkpoint["optimizer_state_dict"]
    )

    scheduler.load_state_dict(
        checkpoint["scheduler_state_dict"]
    )

    scaler.load_state_dict(
        checkpoint["scaler_state_dict"]
    )

    return (
        checkpoint["step"],
        checkpoint.get("train_loss", float("inf")),
        checkpoint.get("best_val_loss", float("inf")),
    )


@torch.no_grad()
def evaluate(
    model: nn.Module,
    tokenizer: ByteBPETokenizer,
    config: ModelConfig,
    device: torch.device,
    max_documents: int = 100,
    max_tokens: int = 10_000,
    batch_size: int = 4,
):
    model.eval()

    dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=config.max_sequence_length,
        max_documents=max_documents,
        max_tokens=max_tokens,
    )

    iterator = iter(dataset)

    total_loss = 0.0
    batches = 0

    while True:
        inputs = []
        targets = []

        for _ in range(batch_size):
            try:
                sample = next(iterator)
            except StopIteration:
                break

            inputs.append(sample["input_ids"])
            targets.append(sample["target_ids"])

        if not inputs:
            break

        input_ids = torch.stack(inputs).to(device)
        target_ids = torch.stack(targets).to(device)

        with torch.autocast(
            device_type=device.type,
            dtype=torch.float16,
            enabled=device.type == "cuda",
        ):
            _, loss = model(
                input_ids,
                targets=target_ids,
            )

        total_loss += loss.item()
        batches += 1

    model.train()

    if batches == 0:
        return float("inf")

    return total_loss / batches


def train(
    max_steps: int = 500,
    sequence_length: int = 128,
    batch_size: int = 4,
    learning_rate: float = 3e-4,
    min_learning_rate: float = 3e-5,
    gradient_accumulation_steps: int = 1,
    max_documents: int = 5_000,
    max_tokens: int = 500_000,
    validation_documents: int = 100,
    validation_tokens: int = 10_000,
    validation_interval: int = 50,
    checkpoint_interval: int = 50,
    resume_from: str | None = None,
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
        print(
            "GPU:",
            torch.cuda.get_device_name(0),
        )

    tokenizer = ByteBPETokenizer.load(
        TOKENIZER_PATH
    )

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

    print(
        f"Parameters: {parameter_count:,}"
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        betas=(0.9, 0.95),
        weight_decay=0.1,
    )

    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max_steps,
        eta_min=min_learning_rate,
    )

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=device.type == "cuda",
    )

    start_step = 0
    best_val_loss = float("inf")

    if resume_from is not None:
        checkpoint_path = Path(resume_from)

        if not checkpoint_path.exists():
            raise FileNotFoundError(
                f"Checkpoint not found: {checkpoint_path}"
            )

        print()
        print(
            f"Loading checkpoint: {checkpoint_path}"
        )

        (
            start_step,
            previous_loss,
            best_val_loss,
        ) = load_checkpoint(
            checkpoint_path,
            model,
            optimizer,
            scheduler,
            scaler,
            device,
        )

        print(
            f"Resumed from step {start_step}"
        )

        print(
            f"Previous loss: {previous_loss:.4f}"
        )

    train_dataset = FineWebTokenDataset(
        tokenizer=tokenizer,
        sequence_length=sequence_length,
        max_documents=max_documents,
        max_tokens=max_tokens,
    )

    train_iterator = iter(train_dataset)

    model.train()

    optimizer.zero_grad(set_to_none=True)

    running_loss = 0.0

    start_time = time.perf_counter()

    print()
    print(
        f"Training steps: {start_step + 1} -> {max_steps}"
    )
    print()

    for step in range(
        start_step + 1,
        max_steps + 1,
    ):
        step_loss = 0.0

        for _ in range(
            gradient_accumulation_steps
        ):
            batch_inputs = []
            batch_targets = []

            for _ in range(batch_size):
                try:
                    sample = next(train_iterator)
                except StopIteration:
                    train_iterator = iter(
                        train_dataset
                    )
                    sample = next(train_iterator)

                batch_inputs.append(
                    sample["input_ids"]
                )

                batch_targets.append(
                    sample["target_ids"]
                )

            input_ids = torch.stack(
                batch_inputs
            ).to(
                device,
                non_blocking=True,
            )

            target_ids = torch.stack(
                batch_targets
            ).to(
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

                scaled_loss = (
                    loss
                    / gradient_accumulation_steps
                )

            scaler.scale(
                scaled_loss
            ).backward()

            step_loss += loss.detach().item()

        scaler.unscale_(optimizer)

        torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            max_norm=1.0,
        )

        scaler.step(optimizer)
        scaler.update()

        optimizer.zero_grad(
            set_to_none=True
        )

        scheduler.step()

        average_step_loss = (
            step_loss
            / gradient_accumulation_steps
        )

        running_loss += average_step_loss

        elapsed = (
            time.perf_counter()
            - start_time
        )

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

        current_lr = optimizer.param_groups[0]["lr"]

        print(
            f"Step {step:04d}/{max_steps} | "
            f"Loss: {average_step_loss:.4f} | "
            f"LR: {current_lr:.7f} | "
            f"Tokens/s: {tokens_per_second:.1f}"
        )

        if (
            step % validation_interval == 0
            or step == max_steps
        ):
            val_loss = evaluate(
                model=model,
                tokenizer=tokenizer,
                config=config,
                device=device,
                max_documents=validation_documents,
                max_tokens=validation_tokens,
                batch_size=batch_size,
            )

            val_perplexity = math.exp(
                min(val_loss, 20)
            )

            print(
                f"Validation | "
                f"Loss: {val_loss:.4f} | "
                f"PPL: {val_perplexity:.2f}"
            )

            if val_loss < best_val_loss:
                best_val_loss = val_loss

                best_path = (
                    CHECKPOINT_DIR
                    / "best.pt"
                )

                save_checkpoint(
                    best_path,
                    model,
                    optimizer,
                    scheduler,
                    scaler,
                    step,
                    average_step_loss,
                    best_val_loss,
                )

                print(
                    f"New best checkpoint: "
                    f"{best_path}"
                )

        if (
            step % checkpoint_interval == 0
            or step == max_steps
        ):
            checkpoint_path = (
                CHECKPOINT_DIR
                / f"checkpoint_step_{step}.pt"
            )

            save_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                scheduler,
                scaler,
                step,
                average_step_loss,
                best_val_loss,
            )

            print(
                f"Checkpoint saved: "
                f"{checkpoint_path}"
            )

    print()
    print("=" * 60)
    print("TRAINING FINISHED")
    print("=" * 60)

    print(
        f"Average loss: "
        f"{running_loss / max_steps:.4f}"
    )

    print(
        f"Best validation loss: "
        f"{best_val_loss:.4f}"
    )


if __name__ == "__main__":
    train(
    max_steps=50,
    validation_interval=10,
    checkpoint_interval=10,
)