import torch
import torch.nn as nn

from model.attention import CausalSelfAttention


class FeedForward(nn.Module):
    def __init__(
        self,
        embedding_dim: int,
        feed_forward_dim: int,
        dropout: float = 0.1,
    ):
        super().__init__()

        self.network = nn.Sequential(
            nn.Linear(embedding_dim, feed_forward_dim),
            nn.GELU(),
            nn.Linear(feed_forward_dim, embedding_dim),
            nn.Dropout(dropout),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


class TransformerBlock(nn.Module):
    def __init__(
        self,
        embedding_dim: int,
        num_heads: int,
        feed_forward_dim: int,
        dropout: float = 0.1,
    ):
        super().__init__()

        self.attention_norm = nn.LayerNorm(embedding_dim)

        self.attention = CausalSelfAttention(
            embedding_dim=embedding_dim,
            num_heads=num_heads,
            dropout=dropout,
        )

        self.feed_forward_norm = nn.LayerNorm(embedding_dim)

        self.feed_forward = FeedForward(
            embedding_dim=embedding_dim,
            feed_forward_dim=feed_forward_dim,
            dropout=dropout,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attention(
            self.attention_norm(x)
        )

        x = x + self.feed_forward(
            self.feed_forward_norm(x)
        )

        return x