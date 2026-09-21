import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel
from model.tokenizer import ByteBPETokenizer


CHECKPOINT = "data/checkpoints/best.pt"
TOKENIZER = "data/tokenizer/nova_tokenizer.json"


device = "cuda" if torch.cuda.is_available() else "cpu"

tokenizer = ByteBPETokenizer.load(TOKENIZER)

model = NovaLanguageModel(ModelConfig())

checkpoint = torch.load(
    CHECKPOINT,
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

model.to(device)
model.eval()


prompt = "User: What is your name?\nAssistant:"

ids = tokenizer.encode(prompt)

input_ids = torch.tensor(
    ids,
    dtype=torch.long,
    device=device,
).unsqueeze(0)


with torch.inference_mode():
    logits, _ = model(input_ids)

next_logits = logits[0, -1]

values, indices = torch.topk(
    next_logits,
    k=20,
)


print("=" * 60)
print("NEXT TOKEN TEST")
print("=" * 60)

for value, index in zip(
    values.tolist(),
    indices.tolist(),
):
    token = tokenizer.id_to_token.get(
        index,
        "<UNKNOWN>",
    )

    print(
        f"{index:6d} | "
        f"{value:8.3f} | "
        f"{repr(token)}"
    )
generated = input_ids.clone()

print("\n" + "=" * 60)
print("GREEDY GENERATION")
print("=" * 60)

for step in range(80):

    context = generated[
        :, -512:
    ]

    with torch.inference_mode():
        logits, _ = model(
            input_ids=context
        )

    next_logits = logits[
        0,
        -1,
    ]

    next_token = torch.argmax(
        next_logits
    ).view(1, 1)

    token_id = next_token.item()

    if token_id == 3:
        break

    generated = torch.cat(
        [
            generated,
            next_token,
        ],
        dim=1,
    )

output_ids = generated[
    0,
    input_ids.size(1):
].tolist()

output = tokenizer.decode(
    output_ids
)

print(output)