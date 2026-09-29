"""Word space and per-round ranking.

Every word in the vocabulary gets a rank from 1 (the secret itself) to N
(least similar), by cosine similarity of GloVe vectors — the same idea
Contexto uses.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SECRET_WORDS_FILE = ROOT / "secret_words.txt"


class WordSpace:
    def __init__(self, vocab: list[str], vectors: np.ndarray):
        if len(vocab) != len(vectors):
            raise ValueError("vocab and vectors differ in length")
        self.vocab = list(vocab)
        self.index = {w: i for i, w in enumerate(self.vocab)}
        v = np.asarray(vectors, dtype=np.float32)
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.vectors = v / norms

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "WordSpace":
        vocab_path, vec_path = data_dir / "vocab.txt", data_dir / "vectors.npy"
        if not vocab_path.exists() or not vec_path.exists():
            raise FileNotFoundError(
                f"No word vectors in {data_dir}. Run `python prepare_vectors.py` first."
            )
        vocab = vocab_path.read_text(encoding="utf-8").split()
        return cls(vocab, np.load(vec_path))

    def __len__(self) -> int:
        return len(self.vocab)

    def __contains__(self, word: str) -> bool:
        return word in self.index

    def ranking(self, secret: str) -> "Ranking":
        idx = self.index[secret]
        sims = self.vectors @ self.vectors[idx]
        order = np.argsort(-sims, kind="stable")
        # The secret is always rank 1, even if another word has an identical vector.
        order = np.concatenate(([idx], order[order != idx]))
        ranks = np.empty(len(order), dtype=np.int32)
        ranks[order] = np.arange(1, len(order) + 1, dtype=np.int32)
        return Ranking(self, secret, order, ranks)


@dataclass
class Ranking:
    space: WordSpace
    secret: str
    order: np.ndarray  # order[r-1] = word index at rank r
    ranks: np.ndarray  # ranks[word index] = rank

    def rank(self, word: str) -> int | None:
        i = self.space.index.get(word)
        return None if i is None else int(self.ranks[i])

    def word_at(self, rank: int) -> str:
        return self.space.vocab[int(self.order[rank - 1])]


# --- bands (match the design: close / warm / cold) ---------------------------

CLOSE_MAX = 300
WARM_MAX = 1500


def band(rank: int) -> str:
    if rank <= CLOSE_MAX:
        return "close"
    if rank <= WARM_MAX:
        return "warm"
    return "cold"


def closeness(rank: int, total: int) -> float:
    """0..1 on a log scale, like Contexto's bars."""
    if total <= 1:
        return 1.0
    return max(0.04, 1 - math.log(rank) / math.log(total))


# --- secret word pool ---------------------------------------------------------

def load_secret_words(space: WordSpace, path: Path = SECRET_WORDS_FILE) -> list[str]:
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        w = line.strip().lower()
        if w and not w.startswith("#") and w in space:
            words.append(w)
    if not words:
        raise ValueError(f"None of the words in {path} are in the vocabulary")
    return sorted(set(words))


def pick_secret(pool: list[str], avoid: set[str], rng: random.Random | None = None) -> str:
    rng = rng or random
    fresh = [w for w in pool if w not in avoid]
    return rng.choice(fresh or pool)
