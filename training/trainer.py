from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from torch.nn.utils import clip_grad_norm_

from model.config import ModelConfig
from model.model import NovaLanguageModel
from training.dataset import create_train_val_dataloaders


@dataclass
class TrainConfig:
    max_steps: int = 12_208

    sequence_length: int = 512
    batch_size: int = 1
    gradient_accumulation_steps: int = 8

    learning_rate: float = 3e-4
    min_learning_rate: float = 3e-5

    warmup_steps: int = 500

    weight_decay: float = 0.1
    max_grad_norm: float = 1.0

    max_train_documents: int = 50_000
    max_train_tokens: int = 10_000_000

    max_validation_documents: int = 500
    max_validation_tokens: int = 100_000

    validation_interval: int = 500
    checkpoint_interval: int = 500

    seed: int = 42

    checkpoint_dir: str = "data/checkpoints"

    resume_from: Optional[str] = "data/checkpoints/best.pt"

    use_amp: bool = True
    amp_dtype: str = "float16"

    save_rng_state: bool = True


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)

    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def capture_rng_state():
    state = {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch": torch.get_rng_state(),
    }

    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()

    return state


def restore_rng_state(state) -> None:
    if not state:
        return

    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(torch.as_tensor(state["torch"], dtype=torch.uint8, device="cpu"))

    if torch.cuda.is_available() and "cuda" in state:
        torch.cuda.set_rng_state_all(
            [
                torch.as_tensor(item, dtype=torch.uint8, device="cpu")
                for item in state["cuda"]
            ]
        )


def build_optimizer(
    model: torch.nn.Module,
    config: TrainConfig,
):
    decay_params = []
    no_decay_params = []

    for name, parameter in model.named_parameters():
        if not parameter.requires_grad:
            continue

        if parameter.ndim >= 2 and "bias" not in name:
            decay_params.append(parameter)
        else:
            no_decay_params.append(parameter)

    return torch.optim.AdamW(
        [
            {
                "params": decay_params,
                "weight_decay": config.weight_decay,
            },
            {
                "params": no_decay_params,
                "weight_decay": 0.0,
            },
        ],
        lr=config.learning_rate,
        betas=(0.9, 0.95),
    )


def get_lr_multiplier(
    step: int,
    config: TrainConfig,
) -> float:
    if step <= config.warmup_steps:
        return max(step, 1) / max(config.warmup_steps, 1)

    if config.max_steps <= config.warmup_steps:
        return 1.0

    progress = (
        step - config.warmup_steps
    ) / (
        config.max_steps - config.warmup_steps
    )

    progress = min(
        max(progress, 0.0),
        1.0,
    )

    cosine = 0.5 * (
        1.0
        + math.cos(
            math.pi * progress
        )
    )

    min_ratio = (
        config.min_learning_rate
        / config.learning_rate
    )

    return (
        min_ratio
        + (1.0 - min_ratio) * cosine
    )


def build_scheduler(
    optimizer,
    config: TrainConfig,
):
    return torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: get_lr_multiplier(
            step,
            config,
        ),
    )


def get_amp_dtype(
    config: TrainConfig,
):
    if config.amp_dtype.lower() == "bfloat16":
        return torch.bfloat16

    return torch.float16


def save_checkpoint(
    path,
    model,
    optimizer,
    scheduler,
    scaler,
    step,
    best_val_loss,
    train_loss,
    tokens_seen,
    config,
):
    payload = {
        "step": step,
        "best_val_loss": best_val_loss,
        "train_loss": train_loss,
        "tokens_seen": tokens_seen,
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "scaler": scaler.state_dict(),
        "train_config": asdict(config),
    }

    if config.save_rng_state:
        payload["rng_state"] = capture_rng_state()

    path = Path(path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    torch.save(
        payload,
        path,
    )


def load_checkpoint(
    path,
    model,
    optimizer,
    device,
):
    checkpoint = torch.load(
        path,
        map_location=device,
        weights_only=False,
    )

    model.load_state_dict(
        checkpoint["model"]
    )

    optimizer.load_state_dict(
        checkpoint["optimizer"]
    )

    return (
        checkpoint.get(
            "step",
            0,
        ),
        checkpoint.get(
            "best_val_loss",
            float("inf"),
        ),
        checkpoint.get(
            "train_loss",
            0.0,
        ),
        checkpoint.get(
            "tokens_seen",
            0,
        ),
        checkpoint.get(
            "rng_state",
        ),
    )


@torch.no_grad()
def evaluate(
    model,
    loader,
    device,
    config,
):
    model.eval()

    total_loss = 0.0
    total_tokens = 0

    use_amp = (
        config.use_amp
        and device.type == "cuda"
    )

    dtype = get_amp_dtype(
        config
    )

    for batch in loader:
        input_ids = batch[
            "input_ids"
        ].to(
            device,
            non_blocking=True,
        )

        target_ids = batch[
            "target_ids"
        ].to(
            device,
            non_blocking=True,
        )

        with torch.autocast(
            device_type=device.type,
            dtype=dtype,
            enabled=use_amp,
        ):
            _, loss = model(
                input_ids,
                target_ids,
            )

        tokens = target_ids.numel()

        total_loss += (
            loss.item() * tokens
        )

        total_tokens += tokens

    model.train()

    if total_tokens == 0:
        return (
            float("inf"),
            float("inf"),
        )

    average_loss = (
        total_loss
        / total_tokens
    )

    perplexity = math.exp(
        min(
            average_loss,
            20.0,
        )
    )

    return (
        average_loss,
        perplexity,
    )


def format_time(
    seconds: float,
) -> str:
    if not math.isfinite(seconds):
        return "--:--:--"

    seconds = max(
        0,
        int(seconds),
    )

    hours, remainder = divmod(
        seconds,
        3600,
    )

    minutes, seconds = divmod(
        remainder,
        60,
    )

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


def train(
    config: TrainConfig,
    model_config: Optional[
        ModelConfig
    ] = None,
):
    set_seed(
        config.seed
    )

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )

    if model_config is None:
        model_config = ModelConfig()

    model = NovaLanguageModel(
        model_config
    ).to(device)

    optimizer = build_optimizer(
        model,
        config,
    )

    use_amp = (
        config.use_amp
        and device.type == "cuda"
    )

    dtype = get_amp_dtype(
        config
    )

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=(
            use_amp
            and dtype == torch.float16
        ),
    )

    tokenizer_path = Path(
        "data/tokenizer/nova_tokenizer.json"
    )

    (
        train_loader,
        validation_loader,
    ) = create_train_val_dataloaders(
        tokenizer_path=tokenizer_path,
        sequence_length=config.sequence_length,
        batch_size=config.batch_size,
        train_max_documents=(
            config.max_train_documents
        ),
        train_max_tokens=(
            config.max_train_tokens
        ),
        validation_max_documents=(
            config.max_validation_documents
        ),
        validation_max_tokens=(
            config.max_validation_tokens
        ),
        seed=config.seed,
    )

    start_step = 0
    best_val_loss = float("inf")
    last_train_loss = 0.0
    tokens_seen = 0

    resume_path = (
        Path(config.resume_from)
        if config.resume_from
        else None
    )

    if resume_path and resume_path.is_file():
        (
            start_step,
            best_val_loss,
            last_train_loss,
            tokens_seen,
            rng_state,
        ) = load_checkpoint(
            resume_path,
            model,
            optimizer,
            device,
        )

        restore_rng_state(
            rng_state
        )

        print(
            f"Resumed from: "
            f"{config.resume_from}"
        )

        print(
            f"Resume step: "
            f"{start_step}"
        )

        print(
            f"Tokens already seen: "
            f"{tokens_seen:,}"
        )

    scheduler = build_scheduler(
        optimizer,
        config,
    )

    if start_step > 0:
        scheduler.last_epoch = start_step

        lr_multiplier = get_lr_multiplier(
            start_step,
            config,
        )

        new_lr = (
            config.learning_rate
            * lr_multiplier
        )

        for group in optimizer.param_groups:
            group["lr"] = new_lr

    print("=" * 72)
    print("NOVA LARGE — CONTINUED PRETRAINING")
    print("=" * 72)

    print(
        f"Device: {device}"
    )

    if device.type == "cuda":
        properties = (
            torch.cuda
            .get_device_properties(0)
        )

        print(
            f"GPU: {properties.name}"
        )

        print(
            "GPU memory: "
            f"{properties.total_memory / 1024**3:.2f} GB"
        )

    parameters = sum(
        parameter.numel()
        for parameter in model.parameters()
    )

    print(
        f"Parameters: "
        f"{parameters:,}"
    )

    print(
        f"Sequence length: "
        f"{config.sequence_length}"
    )

    print(
        f"Batch size: "
        f"{config.batch_size}"
    )

    print(
        "Gradient accumulation: "
        f"{config.gradient_accumulation_steps}"
    )

    print(
        "Effective batch size: "
        f"{config.batch_size * config.gradient_accumulation_steps}"
    )

    print(
        f"Learning rate: "
        f"{config.learning_rate}"
    )

    print(
        f"Warmup steps: "
        f"{config.warmup_steps}"
    )

    print(
        f"Max steps: "
        f"{config.max_steps}"
    )

    print(
        "Target tokens: "
        f"{config.max_steps * config.batch_size * config.gradient_accumulation_steps * config.sequence_length:,}"
    )

    print(
        f"Current tokens: "
        f"{tokens_seen:,}"
    )

    print(
        f"AMP: "
        f"{use_amp} ({config.amp_dtype})"
    )

    print("=" * 72)

    train_iterator = iter(
        train_loader
    )

    optimizer.zero_grad(
        set_to_none=True
    )

    total_start = time.perf_counter()
    window_start = total_start
    window_tokens = 0

    for step in range(
        start_step + 1,
        config.max_steps + 1,
    ):
        model.train()

        accumulated_loss = 0.0

        for _ in range(
            config.gradient_accumulation_steps
        ):
            try:
                batch = next(
                    train_iterator
                )

            except StopIteration:
                train_iterator = iter(
                    train_loader
                )

                batch = next(
                    train_iterator
                )

            input_ids = batch[
                "input_ids"
            ].to(
                device,
                non_blocking=True,
            )

            target_ids = batch[
                "target_ids"
            ].to(
                device,
                non_blocking=True,
            )

            with torch.autocast(
                device_type=device.type,
                dtype=dtype,
                enabled=use_amp,
            ):
                _, loss = model(
                    input_ids,
                    target_ids,
                )

                loss_for_backward = (
                    loss
                    / config.gradient_accumulation_steps
                )

            if use_amp:
                scaler.scale(
                    loss_for_backward
                ).backward()
            else:
                loss_for_backward.backward()

            accumulated_loss += (
                loss.item()
            )

            batch_tokens = (
                target_ids.numel()
            )

            tokens_seen += batch_tokens

            window_tokens += (
                batch_tokens
            )

        if use_amp:
            scaler.unscale_(
                optimizer
            )

        grad_norm = clip_grad_norm_(
            model.parameters(),
            config.max_grad_norm,
        )

        if use_amp:
            scaler.step(
                optimizer
            )

            scaler.update()

        else:
            optimizer.step()

        optimizer.zero_grad(
            set_to_none=True
        )

        scheduler.step()

        last_train_loss = (
            accumulated_loss
            / config.gradient_accumulation_steps
        )

        elapsed = (
            time.perf_counter()
            - window_start
        )

        tokens_per_second = (
            window_tokens
            / max(
                elapsed,
                1e-9,
            )
        )

        steps_done = max(
            step - start_step,
            1,
        )

        average_step_time = (
            time.perf_counter()
            - total_start
        ) / steps_done

        remaining_steps = (
            config.max_steps
            - step
        )

        eta = (
            remaining_steps
            * average_step_time
        )

        if (
            step == start_step + 1
            or step % 10 == 0
            or step == config.max_steps
        ):
            memory = ""

            if device.type == "cuda":
                allocated = (
                    torch.cuda
                    .memory_allocated()
                    / 1024**3
                )

                reserved = (
                    torch.cuda
                    .memory_reserved()
                    / 1024**3
                )

                peak = (
                    torch.cuda
                    .max_memory_allocated()
                    / 1024**3
                )

                memory = (
                    f" | VRAM: "
                    f"{allocated:.2f}/"
                    f"{reserved:.2f} GB"
                    f" | Peak: "
                    f"{peak:.2f} GB"
                )

            print(
                f"Step {step:05d}/"
                f"{config.max_steps} | "
                f"Loss: "
                f"{last_train_loss:.4f} | "
                f"LR: "
                f"{optimizer.param_groups[0]['lr']:.7f} | "
                f"Tok/s: "
                f"{tokens_per_second:.1f} | "
                f"Grad: "
                f"{float(grad_norm):.3f} | "
                f"ETA: "
                f"{format_time(eta)}"
                f"{memory}"
            )

            window_start = (
                time.perf_counter()
            )

            window_tokens = 0

        should_validate = (
            step % config.validation_interval == 0
            or step == config.max_steps
        )

        if should_validate:
            validation_loss, validation_ppl = (
                evaluate(
                    model,
                    validation_loader,
                    device,
                    config,
                )
            )

            print(
                f"Validation | "
                f"Loss: "
                f"{validation_loss:.4f} | "
                f"PPL: "
                f"{validation_ppl:.2f}"
            )

            if validation_loss < best_val_loss:
                best_val_loss = (
                    validation_loss
                )

                save_checkpoint(
                    Path(
                        config.checkpoint_dir
                    ) / "best.pt",
                    model,
                    optimizer,
                    scheduler,
                    scaler,
                    step,
                    best_val_loss,
                    last_train_loss,
                    tokens_seen,
                    config,
                )

                print(
                    "Saved: best.pt"
                )

        should_checkpoint = (
            step % config.checkpoint_interval == 0
            or step == config.max_steps
        )

        if should_checkpoint:
            checkpoint_dir = Path(
                config.checkpoint_dir
            )

            save_checkpoint(
                checkpoint_dir / "last.pt",
                model,
                optimizer,
                scheduler,
                scaler,
                step,
                best_val_loss,
                last_train_loss,
                tokens_seen,
                config,
            )

            save_checkpoint(
                checkpoint_dir
                / f"checkpoint_step_{step}.pt",
                model,
                optimizer,
                scheduler,
                scaler,
                step,
                best_val_loss,
                last_train_loss,
                tokens_seen,
                config,
            )

            print(
                f"Saved checkpoint "
                f"at step {step}"
            )

    print("=" * 72)
    print("TRAINING COMPLETE")
    print("=" * 72)

    print(
        f"Final step: "
        f"{config.max_steps}"
    )

    print(
        f"Tokens seen: "
        f"{tokens_seen:,}"
    )

    print(
        f"Best validation loss: "
        f"{best_val_loss:.4f}"
    )

    print("=" * 72)


if __name__ == "__main__":
    config = TrainConfig(
        max_steps=12_208,

        sequence_length=512,

        batch_size=1,

        gradient_accumulation_steps=8,

        learning_rate=3e-4,

        min_learning_rate=3e-5,

        warmup_steps=500,

        weight_decay=0.1,

        max_grad_norm=1.0,

        max_train_documents=50_000,

        max_train_tokens=10_000_000,

        max_validation_documents=500,

        max_validation_tokens=100_000,

        validation_interval=500,

        checkpoint_interval=500,

        seed=42,

        checkpoint_dir="data/checkpoints",

        resume_from="data/checkpoints/best.pt",

        use_amp=True,

        amp_dtype="float16",

        save_rng_state=True,
    )

    train(config)