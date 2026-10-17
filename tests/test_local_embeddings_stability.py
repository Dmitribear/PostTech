"""Contract: phrase representations cannot depend on unrelated FAQ examples."""
from threading import Lock
from types import SimpleNamespace

import numpy as np

from app.services.local_embeddings import LocalEmbedder


class BatchSensitiveSession:
    def run(self, _outputs, fields):
        tokens = fields["input_ids"].astype(np.float32)
        # Model a global dynamic-quantization scale influenced by every input.
        scale = tokens.max()
        return [np.stack((tokens / scale, np.ones_like(tokens)), axis=-1)]


class Tokenizer:
    def encode_batch(self, texts):
        size = max(map(len, texts))
        return [SimpleNamespace(ids=[ord(c) for c in text] + [0] * (size - len(text)),
                                attention_mask=[1] * len(text) + [0] * (size - len(text)),
                                type_ids=[0] * size) for text in texts]


def test_adding_reordering_or_batching_phrases_does_not_change_their_vectors():
    embedder = LocalEmbedder.__new__(LocalEmbedder)
    embedder.tokenizer = Tokenizer()
    embedder.session = BatchSensitiveSession()
    embedder.input_names = {"input_ids", "attention_mask", "token_type_ids"}
    embedder.lock = Lock()
    expected = embedder.encode(["ab"])[0]
    np.testing.assert_array_equal(embedder.encode(["ab", "long unrelated text"])[0], expected)
    np.testing.assert_array_equal(embedder.encode(["Ещё одна фраза", "ab"])[1], expected)
