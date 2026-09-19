from model.tokenizer import ByteBPETokenizer, TokenizerConfig


texts = [
    "hello world",
    "hello python",
    "python is powerful",
    "def hello(name):",
    "    return f\"Hello {name}\"",
    "سلام دنیا",
    "هوش مصنوعی",
]

tokenizer = ByteBPETokenizer(
    TokenizerConfig(
        vocab_size=1000,
        min_frequency=2,
    )
)

tokenizer.train(texts)

text = "hello python"
encoded = tokenizer.encode(text)
decoded = tokenizer.decode(encoded)

print("Vocabulary:", tokenizer.vocab_size)
print("Text:", text)
print("Encoded:", encoded)
print("Decoded:", decoded)

if decoded != text:
    raise AssertionError(
        f"Tokenizer round-trip failed:\n"
        f"Original: {text!r}\n"
        f"Decoded:  {decoded!r}"
    )

print("Tokenizer test passed.")