import torch

from model.transformer import FeedForward, TransformerBlock


def test_feed_forward_shape():
    network = FeedForward(
        embedding_dim=128,
        feed_forward_dim=512,
        dropout=0.0,
    )

    x = torch.randn(2, 16, 128)
    output = network(x)

    assert output.shape == x.shape


def test_transformer_block_shape():
    block = TransformerBlock(
        embedding_dim=128,
        num_heads=8,
        feed_forward_dim=512,
        dropout=0.0,
    )

    x = torch.randn(2, 16, 128)
    output = block(x)

    assert output.shape == x.shape


def test_transformer_block_finite_output():
    block = TransformerBlock(
        embedding_dim=128,
        num_heads=8,
        feed_forward_dim=512,
        dropout=0.0,
    )

    x = torch.randn(2, 16, 128)
    output = block(x)

    assert torch.isfinite(output).all()


def test_transformer_block_backward():
    block = TransformerBlock(
        embedding_dim=128,
        num_heads=8,
        feed_forward_dim=512,
        dropout=0.0,
    )

    x = torch.randn(
        2,
        16,
        128,
        requires_grad=True,
    )

    output = block(x)
    loss = output.mean()
    loss.backward()

    assert x.grad is not None
    assert torch.isfinite(x.grad).all()


if __name__ == "__main__":
    test_feed_forward_shape()
    test_transformer_block_shape()
    test_transformer_block_finite_output()
    test_transformer_block_backward()

    print("Transformer tests passed.")