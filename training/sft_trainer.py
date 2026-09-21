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


CHECKPOINT_PATH = "data/checkpoints/best.pt"
OUTPUT_PATH = "data/checkpoints/sft_test.pt"

TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"
DATASET_PATH = "data/instruction/nova_instructions.jsonl"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

BATCH_SIZE = 2
GRADIENT_ACCUMULATION = 4

MAX_SEQUENCE_LENGTH = 512

LEARNING_RATE = 1e-5
WEIGHT_DECAY = 0.01
MAX_GRAD_NORM = 1.0

EPOCHS = 3

LOG_EVERY = 5


def set_seed(seed=42):
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

    config = ModelConfig()

    model = NovaLanguageModel(config)

    checkpoint = torch.load(
        CHECKPOINT_PATH,
        map_location="cpu",
        weights_only=False,
    )

    if "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]

    elif "model" in checkpoint:
        state_dict = checkpoint["model"]

    else:
        state_dict = checkpoint

    model.load_state_dict(state_dict)

    model = model.to(DEVICE)

    return model, tokenizer


def build_dataloader(tokenizer):
    dataset = InstructionDataset(
        data_path=DATASET_PATH,
        tokenizer=tokenizer,
        max_sequence_length=MAX_SEQUENCE_LENGTH,
    )

    dataloader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
        collate_fn=instruction_collate_fn,
    )

    return dataset, dataloader


def save_checkpoint(
    model,
    optimizer,
    epoch,
    optimizer_step,
    loss,
):
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "epoch": epoch,
        "step": optimizer_step,
        "loss": loss,
        "config": ModelConfig().__dict__,
    }

    temp_path = OUTPUT_PATH + ".tmp"

    torch.save(
        checkpoint,
        temp_path,
    )

    os.replace(
        temp_path,
        OUTPUT_PATH,
    )

    print(
        f"Saved checkpoint: {OUTPUT_PATH}"
    )


def main():
    print("=" * 72)
    print("NOVA SFT TRAINER")
    print("=" * 72)

    print(f"Device: {DEVICE}")
    print(f"Base checkpoint: {CHECKPOINT_PATH}")
    print(f"Dataset: {DATASET_PATH}")
    print(f"Output: {OUTPUT_PATH}")
    print(f"Batch size: {BATCH_SIZE}")
    print(
        f"Gradient accumulation: "
        f"{GRADIENT_ACCUMULATION}"
    )
    print(f"Learning rate: {LEARNING_RATE}")
    print(f"Epochs: {EPOCHS}")

    print("=" * 72)

    set_seed(42)

    model, tokenizer = load_model()

    dataset, dataloader = build_dataloader(
        tokenizer
    )

    print()
    print(
        f"Dataset samples: {len(dataset)}"
    )
    print(
        f"Steps per epoch: {len(dataloader)}"
    )

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
        betas=(0.9, 0.95),
    )

    model.train()

    optimizer.zero_grad(
        set_to_none=True
    )

    optimizer_step = 0
    micro_step = 0

    epoch_loss = 0.0
    accumulated_loss = 0.0

    start_time = time.time()

    for epoch in range(EPOCHS):

        print()
        print("=" * 72)
        print(
            f"EPOCH {epoch + 1}/{EPOCHS}"
        )
        print("=" * 72)

        epoch_loss = 0.0
        accumulated_loss = 0.0

        for batch_idx, batch in enumerate(
            dataloader
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

            logits, loss = model(
                input_ids=input_ids,
                targets=labels,
            )

            if loss is None:
                raise RuntimeError(
                    "Model did not return a loss."
                )

            loss_value = loss.item()

            epoch_loss += loss_value
            accumulated_loss += loss_value

            loss_for_backward = (
                loss
                / GRADIENT_ACCUMULATION
            )

            loss_for_backward.backward()

            micro_step += 1

            should_step = (
                micro_step
                % GRADIENT_ACCUMULATION
                == 0
            )

            is_last_batch = (
                batch_idx
                == len(dataloader) - 1
            )

            if should_step or is_last_batch:

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
                    / min(
                        GRADIENT_ACCUMULATION,
                        micro_step
                        % GRADIENT_ACCUMULATION
                        if micro_step
                        % GRADIENT_ACCUMULATION
                        != 0
                        else GRADIENT_ACCUMULATION,
                    )
                )

                accumulated_loss = 0.0

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

        mean_epoch_loss = (
            epoch_loss
            / len(dataloader)
        )

        print()
        print(
            f"Epoch {epoch + 1} complete."
        )
        print(
            f"Average loss: "
            f"{mean_epoch_loss:.4f}"
        )

        save_checkpoint(
            model=model,
            optimizer=optimizer,
            epoch=epoch + 1,
            optimizer_step=optimizer_step,
            loss=mean_epoch_loss,
        )

    elapsed = (
        time.time()
        - start_time
    )

    print()
    print("=" * 72)
    print("SFT TEST COMPLETE")
    print("=" * 72)
    print(
        f"Epochs: {EPOCHS}"
    )
    print(
        f"Optimizer steps: "
        f"{optimizer_step}"
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