"""Tiny Ollama client over its local HTTP API, standard library only.

API reference: https://github.com/ollama/ollama/blob/main/docs/api.md
Change the models without touching code:  NOVELTY_CHAT_MODEL=mistral python3 -m novelty.gui
"""
import http.client
import json
import os
import socket
import urllib.error
import urllib.request

from ..errors import Unavailable

CHAT_MODEL = os.environ.get("NOVELTY_CHAT_MODEL", "llama3.2")
EMBED_MODEL = os.environ.get("NOVELTY_EMBED_MODEL", "nomic-embed-text")
TIMEOUT = 180     # seconds; a small model on a laptop CPU can be slow on its first answer
EMBED_BATCH = 64  # texts per /api/embed call, so a whole novel is not one giant request


def host():
    h = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")  # same variable the ollama command uses
    if h.startswith("0.0.0.0"):
        h = "127.0.0.1" + h[len("0.0.0.0"):]  # 0.0.0.0 is a listen address, not one you can connect to
    return (h if h.startswith("http") else "http://" + h).rstrip("/")


def _post(path, body):
    model = body.get("model")
    req = urllib.request.Request(host() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:  # Ollama answered with an error (subclass of URLError: catch it first)
        try:
            msg = json.loads(e.read()).get("error", "")
        except ValueError:
            msg = ""
        if e.code == 404 or "not found" in msg:
            raise Unavailable(f'The AI model "{model}" is not installed. Run:  ollama pull {model}') from None
        raise Unavailable(f"Ollama error {e.code}: {msg or e.reason}") from None
    except socket.timeout:
        raise Unavailable("Ollama took too long to answer. Try again, or use a smaller model.") from None
    except (urllib.error.URLError, ConnectionError) as e:
        if isinstance(getattr(e, "reason", None), socket.timeout):
            raise Unavailable("Ollama took too long to answer. Try again, or use a smaller model.") from None
        raise Unavailable("Ollama is not running. Start the Ollama app (or run 'ollama serve') "
                          "and try again.") from None
    except (ValueError, http.client.HTTPException):  # something else is listening on the port
        raise Unavailable(f"Unexpected reply from {host()}. Is that really Ollama?") from None


def chat(system, prompt, model=None):
    """One question, one answer (no streaming). Returns the answer text."""
    r = _post("/api/chat", {
        "model": model or CHAT_MODEL,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 4096},  # low temperature: stick to the given facts
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    })
    try:
        return r["message"]["content"].strip()
    except (KeyError, TypeError, AttributeError):
        raise Unavailable("Ollama sent back an empty answer.") from None


def embed(texts, model=None):
    """Returns one vector (list of floats) per text."""
    model = model or EMBED_MODEL
    out = []
    for i in range(0, len(texts), EMBED_BATCH):
        r = _post("/api/embed", {"model": model, "input": texts[i:i + EMBED_BATCH]})
        vectors = r.get("embeddings") if isinstance(r, dict) else None
        if not vectors or len(vectors) != len(texts[i:i + EMBED_BATCH]):
            raise Unavailable(f'"{model}" did not return embeddings. Is it an embedding model?')
        out += vectors
    return out
