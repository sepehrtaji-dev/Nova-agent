from __future__ import annotations

import math
import os
import random
import signal
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
from torch.nn.utils import clip_grad_norm_

from model.config import ModelConfig
from model.model import NovaLanguageModel
from training.dataset import create_train_val_dataloaders


CHECKPOINT_DIR = Path("data/checkpoints")

BEST_CHECKPOINT = CHECKPOINT_DIR / "best.pt"
LONG_CHECKPOINT = CHECKPOINT_DIR / "long_train.pt"

TOKENIZER_PATH = Path(
    "data/tokenizer/nova_tokenizer.json"
)

SEQUENCE_LENGTH = 512
BATCH_SIZE = 1
GRADIENT_ACCUMULATION_STEPS = 8

LEARNING_RATE = 3e-4
MIN_LEARNING_RATE = 3e-5

WARMUP_STEPS = 500

WEIGHT_DECAY = 0.1
MAX_GRAD_NORM = 1.0

TARGET_NEW_TOKENS = 120_000_000

TOKENS_PER_STEP = (
    SEQUENCE_LENGTH
    * BATCH_SIZE
    * GRADIENT_ACCUMULATION_STEPS
)

TARGET_STEPS = math.ceil(
    TARGET_NEW_TOKENS / TOKENS_PER_STEP
)

VALIDATION_INTERVAL = 500
CHECKPOINT_INTERVAL = 500

VALIDATION_MAX_TOKENS = 100_000

SEED = 42

AMP_DTYPE = torch.float16

PRINT_INTERVAL = 10


STOP_REQUESTED = False


def handle_stop_signal(signum, frame):
    global STOP_REQUESTED

    STOP_REQUESTED = True

    print()
    print("=" * 72)
    print("STOP REQUEST RECEIVED")
    print("Saving current training state...")
    print("=" * 72)


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
    torch.set_rng_state(
        torch.as_tensor(
            state["torch"],
            dtype=torch.uint8,
            device="cpu",
        )
    )

    if torch.cuda.is_available() and "cuda" in state:
        torch.cuda.set_rng_state_all(
            [
                torch.as_tensor(
                    item,
                    dtype=torch.uint8,
                    device="cpu",
                )
                for item in state["cuda"]
            ]
        )


def build_optimizer(model):
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
                "weight_decay": WEIGHT_DECAY,
            },
            {
                "params": no_decay_params,
                "weight_decay": 0.0,
            },
        ],
        lr=LEARNING_RATE,
        betas=(0.9, 0.95),
    )


def get_lr_multiplier(step: int) -> float:
    if step <= WARMUP_STEPS:
        return max(step, 1) / WARMUP_STEPS

    if TARGET_STEPS <= WARMUP_STEPS:
        return 1.0

    progress = (
        step - WARMUP_STEPS
    ) / (
        TARGET_STEPS - WARMUP_STEPS
    )

    progress = min(
        max(progress, 0.0),
        1.0,
    )

    cosine = (
        0.5
        * (
            1.0
            + math.cos(
                math.pi * progress
            )
        )
    )

    return (
        MIN_LEARNING_RATE / LEARNING_RATE
        + (
            1.0
            - MIN_LEARNING_RATE / LEARNING_RATE
        )
        * cosine
    )


def build_scheduler(optimizer):
    return torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lr_lambda=get_lr_multiplier,
    )


def force_scheduler_position(
    optimizer,
    scheduler,
    step: int,
):
    scheduler.last_epoch = step
    scheduler._step_count = step + 1

    multiplier = get_lr_multiplier(step)

    for group in optimizer.param_groups:
        group["lr"] = (
            LEARNING_RATE
            * multiplier
        )

    scheduler.base_lrs = [
        LEARNING_RATE
        for _ in optimizer.param_groups
    ]


def atomic_save(
    path: Path,
    payload: dict,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    torch.save(
        payload,
        temporary_path,
    )

    os.replace(
        temporary_path,
        path,
    )


def save_checkpoint(
    path: Path,
    model,
    optimizer,
    scheduler,
    scaler,
    step: int,
    best_val_loss: float,
    last_train_loss: float,
    tokens_seen: int,
):
    payload = {
        "model": model.state_dict(),
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "scaler": scaler.state_dict(),
        "step": step,
        "best_val_loss": best_val_loss,
        "train_loss": last_train_loss,
        "tokens_seen": tokens_seen,
        "rng_state": capture_rng_state(),
        "config": {
            "sequence_length": SEQUENCE_LENGTH,
            "batch_size": BATCH_SIZE,
            "gradient_accumulation_steps": (
                GRADIENT_ACCUMULATION_STEPS
            ),
            "learning_rate": LEARNING_RATE,
            "min_learning_rate": MIN_LEARNING_RATE,
            "warmup_steps": WARMUP_STEPS,
            "target_new_tokens": TARGET_NEW_TOKENS,
            "target_steps": TARGET_STEPS,
            "validation_interval": VALIDATION_INTERVAL,
            "checkpoint_interval": CHECKPOINT_INTERVAL,
            "seed": SEED,
        },
    }

    atomic_save(
        path,
        payload,
    )


@torch.no_grad()
def evaluate(
    model,
    loader,
    device,
):
    model.eval()

    total_loss = 0.0
    total_tokens = 0

    for input_ids, target_ids in loader:
        input_ids = input_ids.to(
            device,
            non_blocking=True,
        )

        target_ids = target_ids.to(
            device,
            non_blocking=True,
        )

        with torch.autocast(
            device_type=device.type,
            dtype=AMP_DTYPE,
            enabled=device.type == "cuda",
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

    return average_loss, perplexity


def format_time(seconds: float) -> str:
    seconds = max(
        int(seconds),
        0,
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


def load_source_checkpoint(
    path: Path,
    model,
    optimizer,
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

    scaler.load_state_dict(
        checkpoint["scaler"]
    )

    best_val_loss = checkpoint.get(
        "best_val_loss",
        float("inf"),
    )

    previous_step = checkpoint.get(
        "step",
        0,
    )

    previous_tokens = checkpoint.get(
        "tokens_seen",
        0,
    )

    previous_train_loss = checkpoint.get(
        "train_loss",
        0.0,
    )

    rng_state = checkpoint.get(
        "rng_state"
    )

    return (
        previous_step,
        previous_tokens,
        previous_train_loss,
        best_val_loss,
        rng_state,
    )


def load_long_checkpoint(
    path: Path,
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

    step = checkpoint.get(
        "step",
        0,
    )

    tokens_seen = checkpoint.get(
        "tokens_seen",
        0,
    )

    train_loss = checkpoint.get(
        "train_loss",
        0.0,
    )

    best_val_loss = checkpoint.get(
        "best_val_loss",
        float("inf"),
    )

    rng_state = checkpoint.get(
        "rng_state"
    )

    return (
        step,
        tokens_seen,
        train_loss,
        best_val_loss,
        rng_state,
    )


def create_loaders():
    return create_train_val_dataloaders(
        tokenizer_path=TOKENIZER_PATH,
        sequence_length=SEQUENCE_LENGTH,
        batch_size=BATCH_SIZE,
        train_max_documents=None,
        train_max_tokens=None,
        validation_max_documents=None,
        validation_max_tokens=VALIDATION_MAX_TOKENS,
        validation_fraction=0.05,
        seed=SEED,
    )


def main():
    global STOP_REQUESTED

    signal.signal(
        signal.SIGINT,
        handle_stop_signal,
    )

    if hasattr(signal, "SIGTERM"):
        signal.signal(
            signal.SIGTERM,
            handle_stop_signal,
        )

    CHECKPOINT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    set_seed(SEED)

    device = torch.device(
        "cuda"
        if torch.cuda.is_available()
        else "cpu"
    )

    model_config = ModelConfig()

    model = NovaLanguageModel(
        model_config
    ).to(device)

    optimizer = build_optimizer(
        model
    )

    scheduler = build_scheduler(
        optimizer
    )

    scaler = torch.amp.GradScaler(
        "cuda",
        enabled=device.type == "cuda",
    )

    (
        train_loader,
        validation_loader,
    ) = create_loaders()

    start_step = 0
    tokens_seen = 0
    last_train_loss = 0.0
    best_val_loss = float("inf")

    if LONG_CHECKPOINT.exists():

        (
            start_step,
            tokens_seen,
            last_train_loss,
            best_val_loss,
            rng_state,
        ) = load_long_checkpoint(
            LONG_CHECKPOINT,
            model,
            optimizer,
            scheduler,
            scaler,
            device,
        )

        restore_rng_state(
            rng_state
        )

        print(
            f"Resumed long training from: "
            f"{LONG_CHECKPOINT}"
        )

    else:

        if not BEST_CHECKPOINT.exists():
            raise FileNotFoundError(
                f"Missing checkpoint: "
                f"{BEST_CHECKPOINT}"
            )

        (
            previous_step,
            previous_tokens,
            previous_train_loss,
            best_val_loss,
            rng_state,
        ) = load_source_checkpoint(
            BEST_CHECKPOINT,
            model,
            optimizer,
            scaler,
            device,
        )

        tokens_seen = previous_tokens
        last_train_loss = previous_train_loss

        restore_rng_state(
            rng_state
        )

        force_scheduler_position(
            optimizer,
            scheduler,
            0,
        )

        print(
            f"Loaded model from: "
            f"{BEST_CHECKPOINT}"
        )

        print(
            f"Previous training step: "
            f"{previous_step}"
        )

        print(
            f"Previous tokens seen: "
            f"{previous_tokens:,}"
        )

        print(
            f"Best validation loss: "
            f"{best_val_loss:.4f}"
        )

        start_step = 0

    parameters = sum(
        parameter.numel()
        for parameter in model.parameters()
    )

    print()
    print("=" * 72)
    print("NOVA LARGE — LONG PRETRAINING")
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

    print(
        f"Parameters: {parameters:,}"
    )

    print(
        f"Sequence length: "
        f"{SEQUENCE_LENGTH}"
    )

    print(
        f"Batch size: "
        f"{BATCH_SIZE}"
    )

    print(
        f"Gradient accumulation: "
        f"{GRADIENT_ACCUMULATION_STEPS}"
    )

    print(
        f"Tokens / optimizer step: "
        f"{TOKENS_PER_STEP:,}"
    )

    print(
        f"Target new tokens: "
        f"{TARGET_NEW_TOKENS:,}"
    )

    print(
        f"Target new steps: "
        f"{TARGET_STEPS:,}"
    )

    print(
        f"Starting step: "
        f"{start_step}"
    )

    print(
        f"Starting total tokens: "
        f"{tokens_seen:,}"
    )

    print(
        f"Learning rate: "
        f"{optimizer.param_groups[0]['lr']:.8f}"
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

    try:
        for step in range(
            start_step + 1,
            TARGET_STEPS + 1,
        ):
            if STOP_REQUESTED:
                break

            model.train()

            accumulated_loss = 0.0

            for _ in range(
                GRADIENT_ACCUMULATION_STEPS
            ):
                if STOP_REQUESTED:
                    break

                try:
                    input_ids, target_ids = next(
                        train_iterator
                    )

                except StopIteration:
                    train_iterator = iter(
                        train_loader
                    )

                    input_ids, target_ids = next(
                        train_iterator
                    )

                input_ids = input_ids.to(
                    device,
                    non_blocking=True,
                )

                target_ids = target_ids.to(
                    device,
                    non_blocking=True,
                )

                with torch.autocast(
                    device_type=device.type,
                    dtype=AMP_DTYPE,
                    enabled=device.type == "cuda",
                ):
                    _, loss = model(
                        input_ids,
                        target_ids,
                    )

                    loss_for_backward = (
                        loss
                        / GRADIENT_ACCUMULATION_STEPS
                    )

                if device.type == "cuda":
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

            if STOP_REQUESTED:
                break

            if device.type == "cuda":
                scaler.unscale_(
                    optimizer
                )

            grad_norm = clip_grad_norm_(
                model.parameters(),
                MAX_GRAD_NORM,
            )

            if device.type == "cuda":
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
                / GRADIENT_ACCUMULATION_STEPS
            )

            elapsed = (
                time.perf_counter()
                - window_start
            )

            tokens_per_second = (
                window_tokens
                / max(elapsed, 1e-9)
            )

            completed_steps = (
                step - start_step
            )

            average_step_time = (
                time.perf_counter()
                - total_start
            ) / max(
                completed_steps,
                1,
            )

            remaining_steps = (
                TARGET_STEPS - step
            )

            eta = (
                remaining_steps
                * average_step_time
            )

            current_lr = (
                optimizer.param_groups[0]["lr"]
            )

            if (
                step == 1
                or step % PRINT_INTERVAL == 0
                or step == TARGET_STEPS
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
                    f"{TARGET_STEPS} | "
                    f"Loss: {last_train_loss:.4f} | "
                    f"LR: {current_lr:.8f} | "
                    f"Tok/s: {tokens_per_second:.1f} | "
                    f"Grad: {float(grad_norm):.3f} | "
                    f"Tokens: {tokens_seen:,} | "
                    f"ETA: {format_time(eta)}"
                    f"{memory}"
                )

                window_start = (
                    time.perf_counter()
                )

                window_tokens = 0

            should_validate = (
                step % VALIDATION_INTERVAL == 0
                or step == TARGET_STEPS
            )

            if should_validate:
                validation_loss, validation_ppl = (
                    evaluate(
                        model,
                        validation_loader,
                        device,
                    )
                )

                print(
                    f"Validation | "
                    f"Loss: {validation_loss:.4f} | "
                    f"PPL: {validation_ppl:.2f}"
                )

                if validation_loss < best_val_loss:
                    previous_best = best_val_loss

                    best_val_loss = (
                        validation_loss
                    )

                    save_checkpoint(
                        BEST_CHECKPOINT,
                        model,
                        optimizer,
                        scheduler,
                        scaler,
                        step,
                        best_val_loss,
                        last_train_loss,
                        tokens_seen,
                    )

                    print(
                        "New best model!"
                    )

                    print(
                        f"Best validation loss: "
                        f"{previous_best:.4f} -> "
                        f"{best_val_loss:.4f}"
                    )

                    print(
                        f"Saved: {BEST_CHECKPOINT}"
                    )

            should_checkpoint = (
                step % CHECKPOINT_INTERVAL == 0
                or step == TARGET_STEPS
            )

            if should_checkpoint:
                save_checkpoint(
                    LONG_CHECKPOINT,
                    model,
                    optimizer,
                    scheduler,
                    scaler,
                    step,
                    best_val_loss,
                    last_train_loss,
                    tokens_seen,
                )

                print(
                    f"Saved rolling checkpoint: "
                    f"{LONG_CHECKPOINT}"
                )

    except KeyboardInterrupt:
        STOP_REQUESTED = True

    finally:
        if STOP_REQUESTED:
            current_step = (
                step
                if "step" in locals()
                else start_step
            )

            save_checkpoint(
                LONG_CHECKPOINT,
                model,
                optimizer,
                scheduler,
                scaler,
                current_step,
                best_val_loss,
                last_train_loss,
                tokens_seen,
            )

            print(
                f"Emergency checkpoint saved: "
                f"{LONG_CHECKPOINT}"
            )

    total_time = (
        time.perf_counter()
        - total_start
    )

    new_tokens = (
        tokens_seen
        - (
            50_003_968
        )
    )

    print()
    print("=" * 72)

    if STOP_REQUESTED:
        print("LONG TRAINING STOPPED SAFELY")
    elif start_step + TARGET_STEPS >= TARGET_STEPS:
        print("LONG TRAINING COMPLETE")

    print("=" * 72)

    print(
        f"Final step: "
        f"{step if 'step' in locals() else start_step}"
    )

    print(
        f"Total tokens seen: "
        f"{tokens_seen:,}"
    )

    print(
        f"Approx. new tokens: "
        f"{new_tokens:,}"
    )

    print(
        f"Best validation loss: "
        f"{best_val_loss:.4f}"
    )

    print(
        f"Runtime: "
        f"{format_time(total_time)}"
    )

    print(
        f"Best checkpoint: "
        f"{BEST_CHECKPOINT}"
    )

    print(
        f"Long checkpoint: "
        f"{LONG_CHECKPOINT}"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()