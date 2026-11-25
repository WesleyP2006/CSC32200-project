"""Retrieval shared by the chatbot (UC-10) and Ask-the-Book (UC-11).

A chunk is a dict {"source", "text", "roles", "owner"}: a few hundred characters of one document, the roles
that may see it, and, for personal data, the one user_id it belongs to (None = not personal).

search() scores every chunk against a question:
- normally by cosine similarity of Ollama embeddings. Each chunk is embedded once and cached in a JSON file
  keyed by its text, so editing a store file only re-embeds the part that changed;
- if the embedding model is not available, by keyword overlap, so RAG keeps working without it.
"""
import hashlib
import json
import math
import os
import re
import tempfile

from ..errors import Unavailable
from . import llm

EVERYONE = ("VS", "RC", "VC", "SU")

# A chunk counts as relevant at or above this score (0..1). If general questions get answered "via RAG",
# raise it; if store questions go to the plain LLM, lower it. See the scores: python3 scripts/chat_cli.py --debug
THRESHOLD = {"embedding": 0.6, "keyword": 0.5}

STOPWORDS = set("""a about also am an and any are as at be been but by can could did do does doing for from get
got had has have hello hey hi how i if in into is it its just know like many me much my of ok okay on or our please
should so some tell than thank thanks that the their them then there these they this to us was we were what when
where which who whom whose why will with would you your yours""".split())


def make_chunks(source, text, roles=EVERYONE, size=500, overlap=100, owner=None):
    return [{"source": source, "text": t, "roles": list(roles), "owner": owner}
            for t in split(text, size, overlap)]


def split(text, size=500, overlap=100):
    """Chunks of at most `size` characters. Short paragraphs are packed together; a paragraph longer than
    `size` is cut at spaces into windows that overlap by about `overlap` characters."""
    overlap = min(overlap, size // 4)
    pieces = []
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())  # undo hard line wraps (Gutenberg texts wrap at ~70 columns)
        while len(para) > size:
            cut = para.rfind(" ", size // 2, size)
            cut = cut if cut > 0 else size
            pieces.append(para[:cut])
            start = para.find(" ", cut - overlap, cut)  # begin the next window on a word boundary
            para = para[start + 1 if start >= 0 else cut:].strip()
        if para:
            pieces.append(para)
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > size:
            chunks.append(cur)
            cur = ""
        cur = cur + "\n" + p if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def search(question, chunks, cache_path):
    """Returns (method, [(score, chunk), ...] best first). method is "embedding" or "keyword"."""
    if not chunks:
        return "keyword", []
    try:
        vectors = _cached_vectors([c["text"] for c in chunks], cache_path)
        q = _unit(llm.embed([_prefix("search_query: ") + question])[0])
        scored = [(sum(a * b for a, b in zip(q, v)), c) for v, c in zip(vectors, chunks)]
        method = "embedding"
    except Unavailable:  # no Ollama or no embedding model: still retrieve, just less cleverly
        scored, method = keyword_scores(question, chunks), "keyword"
    scored.sort(key=lambda sc: -sc[0])
    return method, scored


# ---- embeddings ----

def _prefix(p):
    return p if "nomic" in llm.EMBED_MODEL else ""  # nomic-embed-text is trained with these task prefixes


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else list(v)  # unit length: cosine similarity is then a plain dot product


def _key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _cached_vectors(texts, cache_path):
    cache = _read_json(cache_path)
    if cache.get("model") != llm.EMBED_MODEL or not isinstance(cache.get("vectors"), dict):
        cache = {"model": llm.EMBED_MODEL, "vectors": {}}
    keys = [_key(t) for t in texts]
    todo = {k: t for k, t in zip(keys, texts) if k not in cache["vectors"]}
    if todo:
        new = llm.embed([_prefix("search_document: ") + t for t in todo.values()])
        cache["vectors"].update({k: [round(x, 5) for x in _unit(v)] for k, v in zip(todo, new)})
        cache["vectors"] = {k: cache["vectors"][k] for k in keys}  # forget chunks that no longer exist
        _write_json(cache_path, cache)
    return [cache["vectors"][k] for k in keys]


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):  # missing or damaged cache: rebuild it
        return {}


def _write_json(path, data):
    """The cache only saves time, so a failed write is ignored."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        pass


# ---- keyword fallback ----

def _stem(w):
    if len(w) > 4:
        if w.endswith("ies"):
            return w[:-3] + "y"
        for suffix in ("ing", "ed", "es", "s"):
            if w.endswith(suffix) and not w.endswith("ss"):
                w = w[:-len(suffix)]
                break
    return w[:-1] if len(w) > 4 and w.endswith("e") else w


def terms(text):
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in STOPWORDS]


def keyword_scores(question, chunks):
    """Share of the question's keywords found in each chunk, rare words weighing more (0..1)."""
    q = set(terms(question))
    if not q:
        return [(0.0, c) for c in chunks]
    sets = [set(terms(c["text"])) for c in chunks]
    n = len(chunks)
    idf = {t: math.log(1 + n / (sum(t in s for s in sets) or 0.5)) for t in q}
    total = sum(idf.values())
    return [(sum(idf[t] for t in q if t in s) / total, c) for s, c in zip(sets, chunks)]
