import torch

from model.attention import CausalSelfAttention


def test_attention_shape():
    batch_size = 2
    sequence_length = 16
    embedding_dim = 256
    num_heads = 8

    attention = CausalSelfAttention(
        embedding_dim=embedding_dim,
        num_heads=num_heads,
        dropout=0.0,
    )

    x = torch.randn(
        batch_size,
        sequence_length,
        embedding_dim,
    )

    output = attention(x)

    assert output.shape == (
        batch_size,
        sequence_length,
        embedding_dim,
    )


def test_attention_causal_behavior():
    torch.manual_seed(42)

    attention = CausalSelfAttention(
        embedding_dim=64,
        num_heads=4,
        dropout=0.0,
    )

    attention.eval()

    first_input = torch.randn(1, 8, 64)

    second_input = first_input.clone()
    second_input[:, 5:] = torch.randn(1, 3, 64)

    first_output = attention(first_input)
    second_output = attention(second_input)

    assert torch.allclose(
        first_output[:, :5],
        second_output[:, :5],
        atol=1e-5,
    )


def test_attention_finite_output():
    attention = CausalSelfAttention(
        embedding_dim=128,
        num_heads=8,
        dropout=0.0,
    )

    x = torch.randn(2, 10, 128)

    output = attention(x)

    assert torch.isfinite(output).all()


if __name__ == "__main__":
    test_attention_shape()
    test_attention_causal_behavior()
    test_attention_finite_output()

    print("Attention tests passed.")