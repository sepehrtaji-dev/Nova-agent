import os
import random
import time

import numpy as np
import torch
from torch.utils.data import DataLoader

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer

from training.instruction_dataset import (
    InstructionDataset,
    instruction_collate_fn,
)


BASE_CHECKPOINT_PATH = (
    "data/checkpoints/pre_sft.pt"
)

OUTPUT_PATH = (
    "data/checkpoints/best.pt"
)

TEMP_OUTPUT_PATH = (
    "data/checkpoints/best.pt.sft_tmp"
)

TOKENIZER_PATH = (
    "data/tokenizer/nova_tokenizer.json"
)

DATASET_PATH = (
    "data/instruction/nova_instructions.jsonl"
)

DEVICE = (
    "cuda"
    if torch.cuda.is_available()
    else "cpu"
)


BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 4

MAX_SEQUENCE_LENGTH = 512

LEARNING_RATE = 5e-6
WEIGHT_DECAY = 0.01
MAX_GRAD_NORM = 1.0

EPOCHS = 3

VALIDATION_FRACTION = 0.10

SEED = 42

LOG_EVERY = 10


def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_model():
    print("Loading tokenizer...")

    tokenizer = ByteBPETokenizer.load(
        TOKENIZER_PATH
    )

    print("Loading model...")

    model = NovaLanguageModel(
        ModelConfig()
    )

    checkpoint = torch.load(
        BASE_CHECKPOINT_PATH,
        map_location="cpu",
        weights_only=False,
    )

    if (
        isinstance(checkpoint, dict)
        and "model_state_dict" in checkpoint
    ):
        state_dict = checkpoint[
            "model_state_dict"
        ]

    elif (
        isinstance(checkpoint, dict)
        and "model" in checkpoint
    ):
        state_dict = checkpoint[
            "model"
        ]

    else:
        state_dict = checkpoint

    model.load_state_dict(
        state_dict
    )

    model = model.to(DEVICE)

    return model, tokenizer


def load_samples():
    import json

    samples = []

    with open(
        DATASET_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            item = json.loads(line)

            if (
                "instruction" not in item
                or "response" not in item
            ):
                continue

            instruction = str(
                item["instruction"]
            ).strip()

            response = str(
                item["response"]
            ).strip()

            if not instruction:
                continue

            if not response:
                continue

            samples.append(
                {
                    "instruction": instruction,
                    "response": response,
                }
            )

    if not samples:
        raise ValueError(
            "No valid instruction samples found."
        )

    rng = random.Random(SEED)

    rng.shuffle(samples)

    validation_count = max(
        1,
        int(
            len(samples)
            * VALIDATION_FRACTION
        ),
    )

    validation_samples = samples[
        :validation_count
    ]

    train_samples = samples[
        validation_count:
    ]

    return (
        train_samples,
        validation_samples,
    )


def build_dataloaders(
    tokenizer,
):
    train_samples, validation_samples = (
        load_samples()
    )

    train_dataset = InstructionDataset(
        data_path=DATASET_PATH,
        tokenizer=tokenizer,
        max_sequence_length=(
            MAX_SEQUENCE_LENGTH
        ),
        samples=train_samples,
    )

    validation_dataset = InstructionDataset(
        data_path=DATASET_PATH,
        tokenizer=tokenizer,
        max_sequence_length=(
            MAX_SEQUENCE_LENGTH
        ),
        samples=validation_samples,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
        collate_fn=instruction_collate_fn,
    )

    validation_loader = DataLoader(
        validation_dataset,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
        collate_fn=instruction_collate_fn,
    )

    return (
        train_dataset,
        validation_dataset,
        train_loader,
        validation_loader,
    )


def save_checkpoint(
    model,
    optimizer,
    epoch,
    optimizer_step,
    train_loss,
    validation_loss,
):
    checkpoint = {
        "model_state_dict": (
            model.state_dict()
        ),
        "optimizer_state_dict": (
            optimizer.state_dict()
        ),
        "epoch": epoch,
        "step": optimizer_step,
        "train_loss": train_loss,
        "validation_loss": (
            validation_loss
        ),
        "config": (
            ModelConfig().__dict__
        ),
    }

    torch.save(
        checkpoint,
        TEMP_OUTPUT_PATH,
    )

    os.replace(
        TEMP_OUTPUT_PATH,
        OUTPUT_PATH,
    )

    print(
        f"Saved BEST checkpoint: "
        f"{OUTPUT_PATH}"
    )


@torch.inference_mode()
def evaluate(
    model,
    dataloader,
):
    model.eval()

    total_loss = 0.0
    total_batches = 0

    for batch in dataloader:
        input_ids = batch[
            "input_ids"
        ].to(
            DEVICE,
            non_blocking=True,
        )

        labels = batch[
            "labels"
        ].to(
            DEVICE,
            non_blocking=True,
        )

        _, loss = model(
            input_ids=input_ids,
            targets=labels,
        )

        if loss is None:
            raise RuntimeError(
                "Model did not return "
                "a validation loss."
            )

        total_loss += loss.item()
        total_batches += 1

    model.train()

    if total_batches == 0:
        raise RuntimeError(
            "Validation dataloader "
            "is empty."
        )

    return (
        total_loss
        / total_batches
    )


def main():
    print("=" * 72)
    print("NOVA SFT TRAINER V2")
    print("=" * 72)

    print(
        f"Device: {DEVICE}"
    )

    print(
        f"Base checkpoint: "
        f"{BASE_CHECKPOINT_PATH}"
    )

    print(
        f"Dataset: "
        f"{DATASET_PATH}"
    )

    print(
        f"Output: "
        f"{OUTPUT_PATH}"
    )

    print(
        f"Batch size: "
        f"{BATCH_SIZE}"
    )

    print(
        f"Gradient accumulation: "
        f"{GRADIENT_ACCUMULATION}"
    )

    print(
        f"Learning rate: "
        f"{LEARNING_RATE}"
    )

    print(
        f"Epochs: "
        f"{EPOCHS}"
    )

    print(
        f"Validation fraction: "
        f"{VALIDATION_FRACTION}"
    )

    print("=" * 72)

    if not os.path.exists(
        BASE_CHECKPOINT_PATH
    ):
        raise FileNotFoundError(
            "Base SFT checkpoint not found:\n"
            f"{BASE_CHECKPOINT_PATH}\n\n"
            "Put your original pre-SFT "
            "170M-token checkpoint there."
        )

    set_seed()

    model, tokenizer = (
        load_model()
    )

    (
        train_dataset,
        validation_dataset,
        train_loader,
        validation_loader,
    ) = build_dataloaders(
        tokenizer
    )

    print()
    print(
        f"Train samples: "
        f"{len(train_dataset)}"
    )

    print(
        f"Validation samples: "
        f"{len(validation_dataset)}"
    )

    print(
        f"Train batches: "
        f"{len(train_loader)}"
    )

    print(
        f"Validation batches: "
        f"{len(validation_loader)}"
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
        betas=(0.9, 0.95),
    )

    best_validation_loss = float(
        "inf"
    )

    optimizer_step = 0

    start_time = time.time()

    optimizer.zero_grad(
        set_to_none=True
    )

    for epoch in range(EPOCHS):

        model.train()

        epoch_loss = 0.0
        epoch_batches = 0

        accumulated_loss = 0.0
        accumulated_batches = 0

        print()
        print("=" * 72)
        print(
            f"EPOCH "
            f"{epoch + 1}/{EPOCHS}"
        )
        print("=" * 72)

        for batch_idx, batch in enumerate(
            train_loader
        ):
            input_ids = batch[
                "input_ids"
            ].to(
                DEVICE,
                non_blocking=True,
            )

            labels = batch[
                "labels"
            ].to(
                DEVICE,
                non_blocking=True,
            )

            _, loss = model(
                input_ids=input_ids,
                targets=labels,
            )

            if loss is None:
                raise RuntimeError(
                    "Model did not return "
                    "a training loss."
                )

            loss_value = loss.item()

            epoch_loss += loss_value
            epoch_batches += 1

            accumulated_loss += (
                loss_value
            )

            accumulated_batches += 1

            loss_for_backward = (
                loss
                / GRADIENT_ACCUMULATION
            )

            loss_for_backward.backward()

            is_last_batch = (
                batch_idx
                == len(train_loader) - 1
            )

            should_step = (
                (
                    batch_idx + 1
                )
                % GRADIENT_ACCUMULATION
                == 0
            )

            if (
                should_step
                or is_last_batch
            ):
                grad_norm = (
                    torch.nn.utils
                    .clip_grad_norm_(
                        model.parameters(),
                        MAX_GRAD_NORM,
                    )
                )

                optimizer.step()

                optimizer.zero_grad(
                    set_to_none=True
                )

                optimizer_step += 1

                average_loss = (
                    accumulated_loss
                    / accumulated_batches
                )

                accumulated_loss = 0.0
                accumulated_batches = 0

                if (
                    optimizer_step
                    % LOG_EVERY
                    == 0
                    or is_last_batch
                ):
                    elapsed = (
                        time.time()
                        - start_time
                    )

                    print(
                        f"Epoch "
                        f"{epoch + 1}/{EPOCHS} | "
                        f"Step "
                        f"{optimizer_step} | "
                        f"Loss: "
                        f"{average_loss:.4f} | "
                        f"Grad: "
                        f"{float(grad_norm):.4f} | "
                        f"Time: "
                        f"{elapsed:.1f}s"
                    )

        train_loss = (
            epoch_loss
            / max(epoch_batches, 1)
        )

        validation_loss = evaluate(
            model,
            validation_loader,
        )

        print()
        print(
            f"Epoch "
            f"{epoch + 1} complete."
        )

        print(
            f"Train loss: "
            f"{train_loss:.4f}"
        )

        print(
            f"Validation loss: "
            f"{validation_loss:.4f}"
        )

        if (
            validation_loss
            < best_validation_loss
        ):
            improvement = (
                best_validation_loss
                - validation_loss
            )

            best_validation_loss = (
                validation_loss
            )

            print(
                f"New best model!"
            )

            print(
                f"Validation improvement: "
                f"{improvement:.4f}"
            )

            save_checkpoint(
                model=model,
                optimizer=optimizer,
                epoch=epoch + 1,
                optimizer_step=(
                    optimizer_step
                ),
                train_loss=train_loss,
                validation_loss=(
                    validation_loss
                ),
            )

        else:
            print(
                "Validation did not improve."
            )

            print(
                "Keeping previous best.pt"
            )

    elapsed = (
        time.time()
        - start_time
    )

    print()
    print("=" * 72)
    print("SFT V2 COMPLETE")
    print("=" * 72)

    print(
        f"Epochs: {EPOCHS}"
    )

    print(
        f"Optimizer steps: "
        f"{optimizer_step}"
    )

    print(
        f"Best validation loss: "
        f"{best_validation_loss:.4f}"
    )

    print(
        f"Runtime: "
        f"{elapsed:.2f}s"
    )

    print(
        f"Checkpoint: "
        f"{OUTPUT_PATH}"
    )

    print("=" * 72)


if __name__ == "__main__":
    main()