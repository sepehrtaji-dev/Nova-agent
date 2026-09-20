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
    max_steps: int = 1000
    sequence_length: int = 256
    batch_size: int = 1
    gradient_accumulation_steps: int = 8

    learning_rate: float = 3e-4
    min_learning_rate: float = 3e-5
    warmup_steps: int = 50
    weight_decay: float = 0.1
    max_grad_norm: float = 1.0

    max_train_documents: int = 10000
    max_train_tokens: int = 2_000_000
    max_validation_documents: int = 200
    max_validation_tokens: int = 50_000

    validation_interval: int = 100
    checkpoint_interval: int = 100

    num_workers: int = 0
    seed: int = 42

    checkpoint_dir: str = "data/checkpoints"
    resume_from: Optional[str] = None

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
    torch.set_rng_state(state["torch"])

    if torch.cuda.is_available() and "cuda" in state:
        torch.cuda.set_rng_state_all(state["cuda"])


def build_optimizer(
    model: torch.nn.Module,
    config: TrainConfig,
):
    decay_params = []
    no_decay_params = []

    for name, param in model.named_parameters():
        if not param.requires_grad:
            continue

        if param.ndim >= 2 and "bias" not in name:
            decay_params.append(param)
        else:
            no_decay_params.append(param)

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


def lr_lambda(
    step: int,
    config: TrainConfig,
) -> float:
    if step < config.warmup_steps:
        return max(step, 1) / max(config.warmup_steps, 1)

    if config.max_steps <= config.warmup_steps:
        return 1.0

    progress = (
        step - config.warmup_steps
    ) / (
        config.max_steps - config.warmup_steps
    )

    progress = min(max(progress, 0.0), 1.0)

    cosine = 0.5 * (
        1.0 + math.cos(math.pi * progress)
    )

    min_ratio = (
        config.min_learning_rate
        / config.learning_rate
    )

    return min_ratio + (
        1.0 - min_ratio
    ) * cosine


def build_scheduler(
    optimizer,
    config: TrainConfig,
):
    return torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: lr_lambda(step, config),
    )


def get_amp_dtype(config: TrainConfig):
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

    torch.save(payload, path)


def load_checkpoint(
    path,
    model,
    optimizer,
    scheduler,
    scaler,
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

    scheduler.load_state_dict(
        checkpoint["scheduler"]
    )

    scaler.load_state_dict(
        checkpoint["scaler"]
    )

    return (
        checkpoint.get("step", 0),
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
            "rng_state"
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

    dtype = get_amp_dtype(config)

    for batch in loader:
        input_ids = batch["input_ids"].to(
            device,
            non_blocking=True,
        )

        target_ids = batch["target_ids"].to(
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
        return float("inf"), float("inf")

    avg_loss = (
        total_loss
        / total_tokens
    )

    perplexity = math.exp(
        min(avg_loss, 20.0)
    )

    return avg_loss, perplexity


def format_time(seconds: float) -> str:
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
    set_seed(config.seed)

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

    scheduler = build_scheduler(
        optimizer,
        config,
    )

    use_amp = (
        config.use_amp
        and device.type == "cuda"
    )

    dtype = get_amp_dtype(config)

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

    train_loader, validation_loader = (
        create_train_val_dataloaders(
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
    )

    start_step = 0
    best_val_loss = float("inf")
    last_train_loss = 0.0
    tokens_seen = 0

    if config.resume_from:
        (
            start_step,
            best_val_loss,
            last_train_loss,
            tokens_seen,
            rng_state,
        ) = load_checkpoint(
            config.resume_from,
            model,
            optimizer,
            scheduler,
            scaler,
            device,
        )

        restore_rng_state(
            rng_state
        )

    print("=" * 68)
    print("NOVA TRAINER V4")
    print("=" * 68)

    print(
        f"Device: {device}"
    )

    if device.type == "cuda":
        props = (
            torch.cuda
            .get_device_properties(0)
        )

        print(
            f"GPU: {props.name}"
        )

        print(
            "GPU memory: "
            f"{props.total_memory / 1024**3:.2f} GB"
        )

    parameters = sum(
        p.numel()
        for p in model.parameters()
    )

    print(
        f"Parameters: {parameters:,}"
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
        "Effective batch: "
        f"{config.batch_size * config.gradient_accumulation_steps}"
    )

    print(
        f"AMP: {use_amp} "
        f"({config.amp_dtype})"
    )

    print(
        f"Training steps: "
        f"{start_step + 1} "
        f"-> {config.max_steps}"
    )

    print("=" * 68)

    train_iter = iter(
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
                    train_iter
                )

            except StopIteration:
                train_iter = iter(
                    train_loader
                )

                batch = next(
                    train_iter
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
            window_tokens += batch_tokens

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

        tokens_per_sec = (
            window_tokens
            / max(elapsed, 1e-9)
        )

        steps_done = max(
            step - start_step,
            1,
        )

        avg_step_time = (
            time.perf_counter()
            - total_start
        ) / steps_done

        eta = (
            config.max_steps - step
        ) * avg_step_time

        if (
            step == 1
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

                memory = (
                    f" | VRAM: "
                    f"{allocated:.2f}/"
                    f"{reserved:.2f} GB"
                )

            print(
                f"Step {step:05d}/"
                f"{config.max_steps} | "
                f"Loss: "
                f"{last_train_loss:.4f} | "
                f"LR: "
                f"{optimizer.param_groups[0]['lr']:.7f} | "
                f"Tok/s: "
                f"{tokens_per_sec:.1f} | "
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

        if (
            step % config.validation_interval == 0
            or step == config.max_steps
        ):
            val_loss, val_ppl = evaluate(
                model,
                validation_loader,
                device,
                config,
            )

            print(
                f"Validation | "
                f"Loss: {val_loss:.4f} | "
                f"PPL: {val_ppl:.2f}"
            )

            if val_loss < best_val_loss:
                best_val_loss = val_loss

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

        if (
            step % config.checkpoint_interval == 0
            or step == config.max_steps
        ):
            save_checkpoint(
                Path(
                    config.checkpoint_dir
                ) / "last.pt",
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
                Path(
                    config.checkpoint_dir
                ) / f"checkpoint_step_{step}.pt",
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

    print("=" * 68)
    print("TRAINING COMPLETE")

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

    print("=" * 68)


if __name__ == "__main__":
    config = TrainConfig(
        max_steps=50,
        sequence_length=256,
        batch_size=1,
        gradient_accumulation_steps=8,
        max_train_documents=5000,
        max_train_tokens=500_000,
        max_validation_documents=100,
        max_validation_tokens=20_000,
        validation_interval=10,
        checkpoint_interval=10,
    )

    train(config)