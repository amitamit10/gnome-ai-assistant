"""Embedding model wrapper (optional dependency: pip install 'gnome-ai-assistant[embed]').

Default `google/embeddinggemma-2` is multilingual and multimodal (text, images, video frames in one vector space). On a CPU
it is slow (about 4 text chunks/s, seconds per image), so for big libraries use the Colab GPU path in docs/ or a smaller
text-only model such as `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (set "embed_model" in config.json).
"""
import os
import threading

from .. import config

GEMMA2 = "google/embeddinggemma-2"


class EmbedMissing(RuntimeError):
    pass


class Embedder:
    def __init__(self, model_id=None, multimodal=None):
        self.model_id = model_id or config.get("embed_model")
        self.multimodal = (self.model_id == GEMMA2) if multimodal is None else multimodal
        self.model = None
        self.lock = threading.Lock()

    @property
    def is_gemma(self):
        return self.model_id == GEMMA2

    def load(self):
        with self.lock:
            if self.model is not None:
                return self.model
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            try:
                import torch
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise EmbedMissing("semantic search needs the embedding extras: "
                                   "pip install 'gnome-ai-assistant[embed]'") from e
            torch.set_num_threads(max(2, (os.cpu_count() or 4) // 2))
            kw = {"model_kwargs": {"torch_dtype": torch.float32}}  # never float16: Gemma gives NaNs
            if self.is_gemma:
                kw["config_kwargs"] = {"audio_config": None, **({} if self.multimodal else {"vision_config": None})}
            self.model = SentenceTransformer(self.model_id, **kw)
            return self.model

    def unload(self):
        with self.lock:
            self.model = None
        import gc
        gc.collect()

    # ---- encoding (all vectors are L2-normalised float32) ----
    def _enc(self, items, **kw):
        import numpy as np
        m = self.load()
        return np.asarray(m.encode(items, normalize_embeddings=True, show_progress_bar=False, batch_size=8, **kw), dtype=np.float32)

    def documents(self, chunks, title=""):
        if self.is_gemma:  # EmbeddingGemma wants a task prefix on documents
            chunks = [f"title: {title or 'none'} | text: {c}" for c in chunks]
        return self._enc(chunks)

    def queries(self, texts):
        return self._enc(texts, **({"prompt_name": "SearchQuery"} if self.is_gemma else {}))

    def images(self, pil_images):
        if not self.multimodal:
            raise EmbedMissing("the configured embedding model is text-only; use google/embeddinggemma-2 for images")
        return self._enc([{"image": im} for im in pil_images])
