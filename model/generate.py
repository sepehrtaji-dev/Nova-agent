import torch

from model.model import NovaLanguageModel
from model.tokenizer import ByteLevelBPETokenizer


@torch.no_grad()
def generate(
    model: NovaLanguageModel,
    tokenizer: ByteLevelBPETokenizer,
    prompt: str,
    max_new_tokens: int = 50,
    temperature: float = 1.0,
    top_k: int | None = 50,
    device: str = "cpu",
) -> str:
    model.eval()

    input_ids = tokenizer.encode(
        prompt,
        add_special_tokens=False,
    )

    input_ids = torch.tensor(
        [input_ids],
        dtype=torch.long,
        device=device,
    )

    for _ in range(max_new_tokens):
        if input_ids.size(1) > model.config.max_sequence_length:
            input_ids = input_ids[
                :, -model.config.max_sequence_length:
            ]

        logits, _ = model(input_ids)

        next_token_logits = logits[:, -1, :]

        if temperature <= 0:
            raise ValueError(
                "temperature must be greater than 0."
            )

        next_token_logits = (
            next_token_logits / temperature
        )

        if top_k is not None:
            top_k = min(
                top_k,
                next_token_logits.size(-1),
            )

            values, _ = torch.topk(
                next_token_logits,
                top_k,
            )

            threshold = values[:, -1].unsqueeze(-1)

            next_token_logits = torch.where(
                next_token_logits < threshold,
                torch.full_like(
                    next_token_logits,
                    float("-inf"),
                ),
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

        if next_token.item() == tokenizer.eos_token_id:
            break

    generated_ids = input_ids[0].tolist()

    return tokenizer.decode(
        generated_ids,
        skip_special_tokens=True,
    )