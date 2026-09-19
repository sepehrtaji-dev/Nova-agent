import torch
import torch.nn as nn

from model.config import ModelConfig
from model.transformer import TransformerBlock


class NovaLanguageModel(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()

        self.config = config

        self.token_embedding = nn.Embedding(
            config.vocab_size,
            config.embedding_dim,
        )

        self.position_embedding = nn.Embedding(
            config.max_sequence_length,
            config.embedding_dim,
        )

        self.embedding_dropout = nn.Dropout(config.dropout)

        self.transformer_blocks = nn.ModuleList(
            [
                TransformerBlock(
                    embedding_dim=config.embedding_dim,
                    num_heads=config.num_heads,
                    feed_forward_dim=config.feed_forward_dim,
                    dropout=config.dropout,
                )
                for _ in range(config.num_layers)
            ]
        )

        self.final_norm = nn.LayerNorm(config.embedding_dim)

        self.lm_head = nn.Linear(
            config.embedding_dim,
            config.vocab_size,
            bias=False,
        )

        self._initialize_weights()

    def _initialize_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(
                    module.weight,
                    mean=0.0,
                    std=0.02,
                )

                if module.bias is not None:
                    nn.init.zeros_(module.bias)

            elif isinstance(module, nn.Embedding):
                nn.init.normal_(
                    module.weight,
                    mean=0.0,
                    std=0.02,
                )

        self.lm_head.weight = self.token_embedding.weight

    def forward(
        self,
        input_ids: torch.Tensor,
        targets: torch.Tensor | None = None,
    ):
        batch_size, sequence_length = input_ids.shape

        if sequence_length > self.config.max_sequence_length:
            raise ValueError(
                "Sequence length exceeds max_sequence_length."
            )

        positions = torch.arange(
            sequence_length,
            device=input_ids.device,
        )

        token_embeddings = self.token_embedding(input_ids)

        position_embeddings = self.position_embedding(
            positions
        ).unsqueeze(0)

        x = token_embeddings + position_embeddings
        x = self.embedding_dropout(x)

        for block in self.transformer_blocks:
            x = block(x)

        x = self.final_norm(x)

        logits = self.lm_head(x)

        loss = None

        if targets is not None:
            loss = nn.functional.cross_entropy(
                logits.reshape(-1, logits.size(-1)),
                targets.reshape(-1),
            )

        return logits, loss