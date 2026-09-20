from model.tokenizer import ByteBPETokenizer

tokenizer = ByteBPETokenizer.load(
    "data/tokenizer/nova_tokenizer.json"
)

print("=" * 60)
print("TOKEN DEBUG")
print("=" * 60)

ids = [22943, 48, 36, 621, 303, 11811]

for token_id in ids:
    token = tokenizer.id_to_token.get(token_id)

    print()
    print("ID:", token_id)
    print("TOKEN:", repr(token))
    print("LENGTH:", len(token) if token else None)

    if token:
        decoded_bytes = tokenizer._token_to_bytes(token)
        print("BYTES:", decoded_bytes)
        print("TEXT:", repr(decoded_bytes.decode("utf-8", errors="replace")))

print()
print("=" * 60)