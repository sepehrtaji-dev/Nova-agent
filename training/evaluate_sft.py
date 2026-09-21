import os

import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer


BASE_CHECKPOINT = "data/checkpoints/best.pt"
SFT_CHECKPOINT = "data/checkpoints/sft_test.pt"
TOKENIZER_PATH = "data/tokenizer/nova_tokenizer.json"

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

MAX_SEQUENCE_LENGTH = 512
MAX_NEW_TOKENS = 80

TEMPERATURE = 0.8
TOP_K = 40


TEST_PROMPTS = [
    "What is your name?",
    "What are you?",
    "What can you do?",
    "Tell me about yourself.",
    "Are you a human?",
    "Do you have feelings?",
    "What should you do when you don't know something?",
    "Can you write Python code?",
    "What is artificial intelligence?",
    "Hello, how are you?",
]


def load_checkpoint(path):
    print(f"Loading checkpoint: {path}")

    config = ModelConfig()
    model = NovaLanguageModel(config)

    checkpoint = torch.load(
        path,
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
    model.eval()

    return model


def sample_next_token(logits):
    logits = logits / TEMPERATURE

    if TOP_K > 0:
        k = min(TOP_K, logits.size(-1))

        values, indices = torch.topk(
            logits,
            k,
            dim=-1,
        )

        filtered_logits = torch.full_like(
            logits,
            float("-inf"),
        )

        filtered_logits.scatter_(
            -1,
            indices,
            values,
        )

        logits = filtered_logits

    probabilities = torch.softmax(
        logits,
        dim=-1,
    )

    return torch.multinomial(
        probabilities,
        num_samples=1,
    )


@torch.no_grad()
def generate(
    model,
    tokenizer,
    prompt,
):
    formatted_prompt = (
        "<bos>User: "
        + prompt
        + "\nAssistant: "
    )

    input_ids = tokenizer.encode(
        formatted_prompt
    )

    if len(input_ids) > MAX_SEQUENCE_LENGTH - 1:
        input_ids = input_ids[
            -(MAX_SEQUENCE_LENGTH - 1):
        ]

    input_ids = torch.tensor(
        input_ids,
        dtype=torch.long,
        device=DEVICE,
    ).unsqueeze(0)

    generated = input_ids.clone()

    for _ in range(MAX_NEW_TOKENS):

        if generated.size(1) >= MAX_SEQUENCE_LENGTH:
            break

        logits, _ = model(
            input_ids=generated,
        )

        next_logits = logits[:, -1, :]

        next_token = sample_next_token(
            next_logits
        )

        generated = torch.cat(
            [
                generated,
                next_token,
            ],
            dim=1,
        )

        token_id = next_token.item()

        if token_id == 3:
            break

    generated_ids = generated[
        0
    ].tolist()

    text = tokenizer.decode(
        generated_ids
    )

    if "Assistant:" in text:
        text = text.split(
            "Assistant:",
            1,
        )[1]

    if "<eos>" in text:
        text = text.split(
            "<eos>",
            1,
        )[0]

    if "User:" in text:
        text = text.split(
            "User:",
            1,
        )[0]

    return text.strip()


def print_result(
    prompt,
    base_output,
    sft_output,
):
    print()
    print("-" * 72)

    print(
        f"USER: {prompt}"
    )

    print()

    print("BASE MODEL:")
    print(base_output)

    print()

    print("SFT MODEL:")
    print(sft_output)


def main():
    print("=" * 72)
    print("NOVA SFT EVALUATION")
    print("=" * 72)

    print(f"Device: {DEVICE}")
    print(
        f"Base checkpoint: "
        f"{BASE_CHECKPOINT}"
    )
    print(
        f"SFT checkpoint: "
        f"{SFT_CHECKPOINT}"
    )
    print(
        f"Tokenizer: "
        f"{TOKENIZER_PATH}"
    )

    print("=" * 72)

    if not os.path.exists(
        BASE_CHECKPOINT
    ):
        raise FileNotFoundError(
            f"Base checkpoint not found: "
            f"{BASE_CHECKPOINT}"
        )

    if not os.path.exists(
        SFT_CHECKPOINT
    ):
        raise FileNotFoundError(
            f"SFT checkpoint not found: "
            f"{SFT_CHECKPOINT}"
        )

    print()
    print("Loading tokenizer...")

    tokenizer = ByteBPETokenizer.load(
        TOKENIZER_PATH
    )

    base_model = load_checkpoint(
        BASE_CHECKPOINT
    )

    sft_model = load_checkpoint(
        SFT_CHECKPOINT
    )

    print()
    print("Models loaded successfully.")

    print()
    print("=" * 72)
    print("RUNNING EVALUATION")
    print("=" * 72)

    for prompt in TEST_PROMPTS:

        base_output = generate(
            base_model,
            tokenizer,
            prompt,
        )

        sft_output = generate(
            sft_model,
            tokenizer,
            prompt,
        )

        print_result(
            prompt,
            base_output,
            sft_output,
        )

    print()
    print("=" * 72)
    print("SFT EVALUATION COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()