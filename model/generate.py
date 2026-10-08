from __future__ import annotations

import torch

from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer
from model.config import ModelConfig


import os

CHECKPOINT = os.getenv("NOVA_CHECKPOINT", "data/checkpoints/best.pt")
TOKENIZER_PATH = os.getenv(
    "NOVA_TOKENIZER_PATH",
    "data/tokenizer/nova_tokenizer.json",
)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@torch.no_grad()
def generate(
    model: NovaLanguageModel,
    tokenizer: ByteBPETokenizer,
    prompt: str,
    max_new_tokens: int = 100,
    temperature: float = 0.8,
    top_k: int | None = 50,
    device: str = DEVICE,
) -> str:
    model.eval()

    if not isinstance(prompt, str):
        prompt = str(prompt)

    if max_new_tokens < 0:
        raise ValueError("max_new_tokens must be non-negative.")

    if temperature <= 0:
        raise ValueError("temperature must be greater than 0.")

    if top_k is not None and top_k < 1:
        raise ValueError("top_k must be None or greater than 0.")

    prompt_ids = tokenizer.encode(prompt)

    if not prompt_ids:
        raise ValueError("prompt must produce at least one token.")

    input_ids = torch.tensor(
        [prompt_ids],
        dtype=torch.long,
        device=device,
    )

    generation_start = min(
        input_ids.size(1),
        model.config.max_sequence_length,
    )

    for _ in range(max_new_tokens):
        if input_ids.size(1) > model.config.max_sequence_length:
            input_ids = input_ids[:, -model.config.max_sequence_length:]

        logits, _ = model(input_ids)
        next_token_logits = logits[:, -1, :]

        next_token_logits = next_token_logits / temperature

        if top_k is not None:
            k = min(top_k, next_token_logits.size(-1))

            values, _ = torch.topk(next_token_logits, k)

            threshold = values[:, -1].unsqueeze(-1)

            next_token_logits = torch.where(
                next_token_logits < threshold,
                torch.full_like(next_token_logits, float("-inf")),
                next_token_logits,
            )

        probabilities = torch.softmax(
            next_token_logits,
            dim=-1,
        )

        next_token = torch.multinomial(
            probabilities,
            num_samples=1,
        )

        input_ids = torch.cat(
            [input_ids, next_token],
            dim=1,
        )

        if next_token.item() == tokenizer.SPECIAL_TOKENS.get("<eos>", 3):
            break

    generated_ids = input_ids[0, generation_start:].tolist()
    return tokenizer.decode(generated_ids)


def load_model():
    print("=" * 60)
    print("NOVA LARGE GENERATION")
    print("=" * 60)

    print(f"Device: {DEVICE}")
    print(f"Checkpoint: {CHECKPOINT}")
    print(f"Tokenizer: {TOKENIZER_PATH}")

    tokenizer = ByteBPETokenizer.load(TOKENIZER_PATH)

    config = ModelConfig()

    model = NovaLanguageModel(config)

    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")
    print("Loading checkpoint...")

    checkpoint = torch.load(
        CHECKPOINT,
        map_location=DEVICE,
        weights_only=True,
    )

    if "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    elif "model" in checkpoint:
        state_dict = checkpoint["model"]
    else:
        state_dict = checkpoint

    model.load_state_dict(state_dict)

    model.to(DEVICE)
    model.eval()

    print("Model loaded successfully.")
    print("=" * 60)

    return model, tokenizer


def main():
    model, tokenizer = load_model()

    print()
    print("Nova is ready.")
    print("Type 'exit' to quit.")
    print()

    while True:
        prompt = input("You: ").strip()

        if prompt.lower() == "exit":
            break

        if not prompt:
            continue

        print("Nova: ", end="", flush=True)

        output = generate(
            model=model,
            tokenizer=tokenizer,
            prompt=prompt,
            max_new_tokens=100,
            temperature=0.8,
            top_k=50,
            device=DEVICE,
        )

        if output.startswith(prompt):
            output = output[len(prompt):]

        print(output)
        print()


if __name__ == "__main__":
    main()