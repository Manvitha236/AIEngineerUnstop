from pathlib import Path
from typing import List
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'

class SimpleVectorStore:
    def __init__(self, dim: int):
        self.index = faiss.IndexFlatIP(dim)
        self.meta: List[str] = []

    def add(self, embeddings: np.ndarray, texts: List[str]):
        self.index.add(embeddings)
        self.meta.extend(texts)

    def search(self, embedding: np.ndarray, k: int = 3):
        D, I = self.index.search(embedding, k)
        results = []
        for score, idx in zip(D[0], I[0]):
            if idx < len(self.meta) and idx >=0:
                results.append((self.meta[idx], float(score)))
        return results

class RagEngine:
    def __init__(self, persist_dir: str = ".rag_store"):
        self.model = SentenceTransformer(MODEL_NAME)
        self.store = SimpleVectorStore(dim=self.model.get_sentence_embedding_dimension())
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(exist_ok=True)
        self.index_path = self.persist_dir / 'index.faiss'
        self.meta_path = self.persist_dir / 'meta.txt'
        self._loaded = False
        self._try_load()

    def build(self, docs: List[str]):
        embeddings = self.model.encode(docs, normalize_embeddings=True)
        self.store.add(embeddings, docs)
        self._persist()

    def retrieve(self, query: str, k: int = 3):
        emb = self.model.encode([query], normalize_embeddings=True)
        return self.store.search(emb, k=k)

    def add_doc(self, text: str):
        emb = self.model.encode([text], normalize_embeddings=True)
        self.store.add(emb, [text])
        self._persist()

    def _persist(self):  # pragma: no cover
        try:
            faiss.write_index(self.store.index, str(self.index_path))
            self.meta_path.write_text("\n".join(self.store.meta), encoding='utf-8')
        except Exception:
            pass

    def _try_load(self):  # pragma: no cover
        if not self.index_path.exists() or not self.meta_path.exists():
            return
        try:
            index = faiss.read_index(str(self.index_path))
            meta = self.meta_path.read_text(encoding='utf-8').splitlines()
            if len(meta) == index.ntotal:
                self.store.index = index
                self.store.meta = meta
                self._loaded = True
        except Exception:
            pass
