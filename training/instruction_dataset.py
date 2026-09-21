import json
from pathlib import Path

import torch
from torch.utils.data import Dataset


class InstructionDataset(Dataset):

    def __init__(
        self,
        data_path,
        tokenizer,
        max_sequence_length=512,
        samples=None,
    ):
        self.data_path = Path(data_path)
        self.tokenizer = tokenizer
        self.max_sequence_length = max_sequence_length

        if samples is not None:
            self.samples = list(samples)
        else:
            self.samples = []

            with self.data_path.open(
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
                        raise ValueError(
                            "Each sample must contain "
                            "'instruction' and 'response'"
                        )

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

                    self.samples.append(
                        {
                            "instruction": instruction,
                            "response": response,
                        }
                    )

        if not self.samples:
            raise ValueError(
                "Instruction dataset is empty"
            )

    def __len__(self):
        return len(self.samples)

    def _encode(self, text):
        return self.tokenizer.encode(text)

    def __getitem__(self, index):
        sample = self.samples[index]

        instruction = sample[
            "instruction"
        ]

        response = sample[
            "response"
        ]

        prompt = (
            "<bos>"
            "User: "
            + instruction
            + "\nAssistant: "
        )

        response_text = (
            response
            + "<eos>"
        )

        prompt_ids = self._encode(
            prompt
        )

        response_ids = self._encode(
            response_text
        )

        available_length = (
            self.max_sequence_length
            - len(prompt_ids)
        )

        if available_length <= 0:
            raise ValueError(
                "Prompt is too long for "
                "max_sequence_length: "
                f"{self.max_sequence_length}"
            )

        response_ids = response_ids[
            :available_length
        ]

        full_ids = (
            prompt_ids
            + response_ids
        )

        if len(full_ids) < 2:
            raise ValueError(
                "Encoded sample is too short."
            )

        input_ids = full_ids[:-1]
        target_ids = full_ids[1:]

        prompt_target_length = min(
            max(len(prompt_ids) - 1, 0),
            len(target_ids),
        )

        labels = target_ids.copy()

        for i in range(
            prompt_target_length
        ):
            labels[i] = -100

        return {
            "input_ids": torch.tensor(
                input_ids,
                dtype=torch.long,
            ),
            "labels": torch.tensor(
                labels,
                dtype=torch.long,
            ),
            "attention_mask": torch.ones(
                len(input_ids),
                dtype=torch.long,
            ),
        }


def instruction_collate_fn(
    batch,
    pad_token_id=0,
):
    if not batch:
        raise ValueError(
            "Empty batch"
        )

    max_length = max(
        item["input_ids"].size(0)
        for item in batch
    )

    input_ids = []
    labels = []
    attention_masks = []

    for item in batch:
        length = item[
            "input_ids"
        ].size(0)

        padding = (
            max_length - length
        )

        input_ids.append(
            torch.cat(
                [
                    item["input_ids"],
                    torch.full(
                        (padding,),
                        pad_token_id,
                        dtype=torch.long,
                    ),
                ]
            )
        )

        labels.append(
            torch.cat(
                [
                    item["labels"],
                    torch.full(
                        (padding,),
                        -100,
                        dtype=torch.long,
                    ),
                ]
            )
        )

        attention_masks.append(
            torch.cat(
                [
                    item["attention_mask"],
                    torch.zeros(
                        padding,
                        dtype=torch.long,
                    ),
                ]
            )
        )

    return {
        "input_ids": torch.stack(
            input_ids
        ),
        "labels": torch.stack(
            labels
        ),
        "attention_mask": torch.stack(
            attention_masks
        ),
    }