import torch

from model.config import ModelConfig
from model.model import NovaLanguageModel


def create_test_model():
    config = ModelConfig(
        vocab_size=1000,
        max_sequence_length=32,
        embedding_dim=128,
        num_layers=2,
        num_heads=8,
        feed_forward_dim=512,
        dropout=0.0,
    )

    return NovaLanguageModel(config)


def test_model_shape():
    model = create_test_model()

    input_ids = torch.randint(
        0,
        1000,
        (2, 16),
    )

    logits, loss = model(input_ids)

    assert logits.shape == (2, 16, 1000)
    assert loss is None


def test_model_loss():
    model = create_test_model()

    input_ids = torch.randint(
        0,
        1000,
        (2, 16),
    )

    targets = torch.randint(
        0,
        1000,
        (2, 16),
    )

    logits, loss = model(
        input_ids,
        targets,
    )

    assert logits.shape == (2, 16, 1000)
    assert loss is not None
    assert torch.isfinite(loss)


def test_model_backward():
    model = create_test_model()

    input_ids = torch.randint(
        0,
        1000,
        (2, 16),
    )

    targets = torch.randint(
        0,
        1000,
        (2, 16),
    )

    _, loss = model(
        input_ids,
        targets,
    )

    loss.backward()

    gradients_exist = any(
        parameter.grad is not None
        for parameter in model.parameters()
        if parameter.requires_grad
    )

    assert gradients_exist

    for parameter in model.parameters():
        if parameter.grad is not None:
            assert torch.isfinite(parameter.grad).all()


def test_sequence_limit():
    model = create_test_model()

    input_ids = torch.randint(
        0,
        1000,
        (1, 33),
    )

    try:
        model(input_ids)
    except ValueError:
        return

    raise AssertionError(
        "Model accepted a sequence longer than the configured limit."
    )


if __name__ == "__main__":
    test_model_shape()
    test_model_loss()
    test_model_backward()
    test_sequence_limit()

    print("Model tests passed.")