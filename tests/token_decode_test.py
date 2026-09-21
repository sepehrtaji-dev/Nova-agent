from model.tokenizer import ByteBPETokenizer

tokenizer = ByteBPETokenizer.load(
    "data/tokenizer/nova_tokenizer.json"
)

text = "My name is Nova."

ids = tokenizer.encode(text)
decoded = tokenizer.decode(ids)

print("Original:")
print(text)

print("\nToken IDs:")
print(ids)

print("\nDecoded:")
print(decoded)

print("\nMATCH:", text == decoded)