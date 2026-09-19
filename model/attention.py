import math

import torch
import torch.nn as nn


class CausalSelfAttention(nn.Module):
    def __init__(
        self,
        embedding_dim: int,
        num_heads: int,
        dropout: float = 0.1,
    ):
        super().__init__()

        if embedding_dim % num_heads != 0:
            raise ValueError(
                "embedding_dim must be divisible by num_heads"
            )

        self.embedding_dim = embedding_dim
        self.num_heads = num_heads
        self.head_dim = embedding_dim // num_heads

        self.q_projection = nn.Linear(embedding_dim, embedding_dim)
        self.k_projection = nn.Linear(embedding_dim, embedding_dim)
        self.v_projection = nn.Linear(embedding_dim, embedding_dim)

        self.output_projection = nn.Linear(
            embedding_dim,
            embedding_dim,
        )

        self.attention_dropout = nn.Dropout(dropout)
        self.output_dropout = nn.Dropout(dropout)

    def _split_heads(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, sequence_length, _ = x.shape

        x = x.view(
            batch_size,
            sequence_length,
            self.num_heads,
            self.head_dim,
        )

        return x.transpose(1, 2)

    def _merge_heads(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, _, sequence_length, _ = x.shape

        x = x.transpose(1, 2).contiguous()

        return x.view(
            batch_size,
            sequence_length,
            self.embedding_dim,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, sequence_length, _ = x.shape

        query = self._split_heads(self.q_projection(x))
        key = self._split_heads(self.k_projection(x))
        value = self._split_heads(self.v_projection(x))

        attention_scores = torch.matmul(
            query,
            key.transpose(-2, -1),
        )

        attention_scores = attention_scores / math.sqrt(
            self.head_dim
        )

        causal_mask = torch.triu(
            torch.ones(
                sequence_length,
                sequence_length,
                device=x.device,
                dtype=torch.bool,
            ),
            diagonal=1,
        )

        attention_scores = attention_scores.masked_fill(
            causal_mask,
            float("-inf"),
        )

        attention_weights = torch.softmax(
            attention_scores,
            dim=-1,
        )

        attention_weights = self.attention_dropout(
            attention_weights
        )

        output = torch.matmul(
            attention_weights,
            value,
        )

        output = self._merge_heads(output)

        output = self.output_projection(output)
        output = self.output_dropout(output)

        return output