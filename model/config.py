from dataclasses import dataclass


@dataclass
class ModelConfig:
    vocab_size: int = 32000
    max_sequence_length: int = 512
    embedding_dim: int = 1024
    num_layers: int = 22
    num_heads: int = 16
    feed_forward_dim: int = 4096
    dropout: float = 0.1
    
    @property
    def head_dim(self) -> int:
        if self.embedding_dim % self.num_heads != 0:
            raise ValueError("embedding_dim must be divisible by num_heads")
        return self.embedding_dim // self.num_heads