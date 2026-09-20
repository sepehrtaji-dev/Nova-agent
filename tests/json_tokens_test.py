from model.tokenizer import ByteBPETokenizer

path = "data/tokenizer/nova_tokenizer.json"

tokenizer = ByteBPETokenizer.load(path)

print("=" * 60)
print("TOKENIZER STRUCTURE DEBUG")
print("=" * 60)

print("token_to_id type:", type(tokenizer.token_to_id))
print("id_to_token type:", type(tokenizer.id_to_token))

print("token_to_id size:", len(tokenizer.token_to_id))
print("id_to_token size:", len(tokenizer.id_to_token))

print()
print("FIRST 20 token_to_id:")
for i, (token, token_id) in enumerate(tokenizer.token_to_id.items()):
    print(repr(token), "->", repr(token_id))
    if i >= 19:
        break

print()
print("FIRST 20 id_to_token:")
for i, (token_id, token) in enumerate(tokenizer.id_to_token.items()):
    print(repr(token_id), "->", repr(token))
    if i >= 19:
        break

print()
print("=" * 60)
print("SPECIFIC IDS")
print("=" * 60)

for token_id in [22943, 48, 36, 621, 303, 11811]:
    print(
        "ID:",
        token_id,
        "| direct:",
        repr(tokenizer.id_to_token.get(token_id))
    )

print()
print("Checking token_to_id values...")

for token in ["<pad>", "<unk>", "<bos>", "<eos>", "<0x20>", "<0x48>"]:
    print(
        repr(token),
        "->",
        repr(tokenizer.token_to_id.get(token))
    )