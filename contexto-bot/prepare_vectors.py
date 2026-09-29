"""Build data/vocab.txt + data/vectors.npy from GloVe (Wikipedia + Gigaword, 100d).

Downloads ~128 MB once, keeps the 50,000 most frequent plain lowercase words
(GloVe files are ordered by frequency), and writes ~20 MB of vectors.

    python prepare_vectors.py                 # download and build
    python prepare_vectors.py --source FILE   # use a local GloVe .txt / .gz
"""
from __future__ import annotations

import argparse
import gzip
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

URL = "https://github.com/RaRe-Technologies/gensim-data/releases/download/glove-wiki-gigaword-100/glove-wiki-gigaword-100.gz"
DATA = Path(__file__).resolve().parent / "data"
WORD = re.compile(r"[a-z]{2,}")


def download(dest: Path) -> None:
    print(f"Downloading {URL}")

    def progress(blocks, block_size, total):
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            print(f"\r  {pct:3d}%", end="", flush=True)

    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(URL, tmp, progress)
    tmp.rename(dest)
    print()


def open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")


def build(source: Path, size: int) -> None:
    vocab, rows = [], []
    with open_text(source) as f:
        for n, line in enumerate(f):
            parts = line.rstrip().split(" ")
            if n == 0 and len(parts) == 2 and all(p.isdigit() for p in parts):
                continue  # word2vec header line
            word = parts[0]
            if WORD.fullmatch(word):
                vocab.append(word)
                rows.append(np.asarray(parts[1:], dtype=np.float32))
                if len(vocab) >= size:
                    break
    DATA.mkdir(exist_ok=True)
    np.save(DATA / "vectors.npy", np.vstack(rows))
    (DATA / "vocab.txt").write_text("\n".join(vocab) + "\n", encoding="utf-8")
    print(f"Wrote {len(vocab):,} words to {DATA}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, help="local GloVe file (.txt or .gz)")
    ap.add_argument("--size", type=int, default=50_000, help="vocabulary size (default 50,000)")
    args = ap.parse_args()
    source = args.source
    if source is None:
        source = DATA / "glove-wiki-gigaword-100.gz"
        if not source.exists():
            DATA.mkdir(exist_ok=True)
            download(source)
    if not source.exists():
        sys.exit(f"{source} not found")
    build(source, args.size)


if __name__ == "__main__":
    main()
