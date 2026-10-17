"""CPU-only multilingual MPNet embeddings; runtime never downloads anything.

Official quantized ONNX export, masked mean pooling, L2 normalization. No Python
model code, PyTorch, LLM server, API key or external inference endpoint is used.
"""

import hashlib
from pathlib import Path
from threading import Lock

import numpy as np

from app.services.jana_errors import JanaUnavailable

MODEL_ID = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
REVISION = "4328cf26390c98c5e3c738b4460a05b95f4911f5"
MODEL_FILES = {
    "onnx/model_quint8_avx2.onnx": "82f6b58b509e6f87a3c181fd08a94376499faa6c344eea0b36214d47d3943e61",
    "tokenizer.json": "2c3387be76557bd40970cec13153b3bbf80407865484b209e655e5e4729076b8",
}
MAX_TOKENS = 128


def file_matches(path: Path, digest: str) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == digest


class LocalEmbedder:
    def __init__(self, model_dir: Path):
        try:
            if not all(file_matches(model_dir / name, digest) for name, digest in MODEL_FILES.items()):
                raise JanaUnavailable("Run python -m scripts.prepare_jana_local first")
            import onnxruntime as ort
            from tokenizers import Tokenizer

            self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
            # Do not silently truncate suffixes containing another question.
            self.tokenizer.no_truncation()
            self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            self.session = ort.InferenceSession(
                str(model_dir / "onnx/model_quint8_avx2.onnx"),
                sess_options=options, providers=["CPUExecutionProvider"],
            )
            self.input_names = {item.name for item in self.session.get_inputs()}
            self.lock = Lock()
        except JanaUnavailable:
            raise
        except Exception as exc:
            raise JanaUnavailable("Local embedding model could not be loaded") from exc

    def encode(self, texts: list[str]) -> np.ndarray:
        batches = []
        try:
            # Dynamic quantization is sensitive to the other texts/padding in
            # a batch. Encode each phrase independently, just like a query, so
            # adding/reordering FAQ examples cannot change existing vectors.
            # Serialize tokenizer + inference access and bound memory use.
            with self.lock:
                for text in texts:
                    tokens = self.tokenizer.encode_batch([text])
                    if any(len(item.ids) > MAX_TOKENS for item in tokens):
                        raise ValueError("Text exceeds the model token limit")
                    fields = {
                        "input_ids": np.array([item.ids for item in tokens], dtype=np.int64),
                        "attention_mask": np.array([item.attention_mask for item in tokens], dtype=np.int64),
                        "token_type_ids": np.array([item.type_ids for item in tokens], dtype=np.int64),
                    }
                    hidden = self.session.run(None, {k: v for k, v in fields.items() if k in self.input_names})[0]
                    mask = fields["attention_mask"][..., None].astype(np.float32)
                    pooled = (hidden * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1)
                    batches.append(pooled / np.linalg.norm(pooled, axis=1, keepdims=True).clip(min=1e-9))
            return np.concatenate(batches)
        except ValueError:
            raise
        except Exception as exc:
            raise JanaUnavailable("Local embedding inference failed") from exc
