"""Chatbot (UC-10) and Ask-the-Book (UC-11) tests. No Ollama needed: a fake stands in for it.

Run from the repo root:  python3 tests/test_ai.py   (also works under pytest)
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from novelty.core import accounts, askbook, chat, llm, rag  # noqa: E402
from novelty.errors import NoveltyError, Unavailable  # noqa: E402
from novelty.store import Store  # noqa: E402

REPO = os.path.join(os.path.dirname(__file__), "..")
REAL_EMBED, REAL_CHAT = llm.embed, llm.chat

# The fake "embedding" is which of these words a text contains, so the tests control what matches what.
TOPICS = ["hour", "desk", "revenue", "balance", "dracula", "stoker", "capital", "france", "harker", "castle", "bought", "sold", "copies"]


class FakeOllama:
    def __init__(self, embed_ok=True, chat_ok=True):
        self.embed_ok, self.chat_ok = embed_ok, chat_ok
        self.embedded, self.prompts = [], []
        llm.embed, llm.chat = self.embed, self.chat
        llm.EMBED_MODEL, llm.CHAT_MODEL = "fake-embed", "fake-chat"

    def embed(self, texts, model=None):
        if not self.embed_ok:
            raise Unavailable('The AI model "fake-embed" is not installed.')
        self.embedded += texts
        topics = [rag.terms(t)[0] for t in TOPICS]  # compare stems: "revenue" is stored as "revenu"
        return [[1.0 if t in set(rag.terms(text)) else 0.0 for t in topics] for text in texts]

    def chat(self, system, prompt, model=None):
        if not self.chat_ok:
            raise Unavailable("Ollama is not running.")
        self.prompts.append(system + "\n" + prompt)
        return "fake answer"


def fresh():
    """A copy of the committed demo data (store_info included) in a temp folder."""
    d = os.path.join(tempfile.mkdtemp(), "data")
    shutil.copytree(os.path.join(REPO, "data"), d, ignore=shutil.ignore_patterns("rag_cache", "texts"))
    s = Store(d)
    users = {u["name"]: u for u in s.users}
    return s, users["Ana"], users["Ben"], users["Admin"]


def raises(fn, *args):
    try:
        fn(*args)
    except NoveltyError as e:
        return str(e)
    raise AssertionError("expected NoveltyError")


def test_split():
    text = "Short one.\n\nShort two.\n\n" + " ".join(f"word{i}" for i in range(400))
    chunks = rag.split(text, size=300, overlap=60)
    assert all(len(c) <= 300 for c in chunks) and chunks[0].startswith("Short one.\nShort two.")
    words = [w for c in chunks for w in c.split()]
    assert words[4:9] == ["word0", "word1", "word2", "word3", "word4"] and words[-1] == "word399"
    assert len(words) > 402  # windows overlap, so some words appear twice
    assert rag.split("") == [] and rag.split("\n\n  \n") == []


def test_store_question_via_rag():
    s, *_ = fresh()
    fake = FakeOllama()
    text, tag = chat.answer(s, "What are the help desk hours?", None)
    assert text == "fake answer" and tag.startswith("via RAG · hours.txt"), tag
    assert "9 am to 6 pm" in fake.prompts[0]


def test_general_question_goes_to_llm():
    s, *_ = fresh()
    fake = FakeOllama()
    assert chat.answer(s, "What is the capital of France?", None) == ("fake answer", "LLM · fake-chat")
    assert "Store information" not in fake.prompts[0] and "capital of France" in fake.prompts[0]
    assert raises(chat.answer, s, "   ", None) == "Type a question first"


def test_finance_only_for_su():
    s, ana, _, admin = fresh()
    accounts.deposit(s, ana, 20)
    accounts.purchase(s, ana, s.books[3])  # Dracula, $9.00
    fake = FakeOllama()
    text, tag = chat.answer(s, "What is the total revenue?", admin)
    assert tag == "via RAG · finance report" and "$9.00 revenue from 1 book sale(s)" in fake.prompts[0]
    for user in (ana, None):
        assert chat.answer(s, "What is the total revenue?", user) == (chat.RESTRICTED, "restricted")
    # refused even though Ana's own balance chunk also passes the threshold: the hidden report matched best
    assert chat.answer(s, "What is the revenue and the balance?", ana) == (chat.RESTRICTED, "restricted")
    assert len(fake.prompts) == 1  # the model never saw the finance report for them


def test_customer_sees_only_own_account():
    s, ana, ben, _ = fresh()
    fake = FakeOllama()
    text, tag = chat.answer(s, "How many books have I bought?", ana)
    assert tag.startswith("via RAG · your account"), tag
    assert "Your balance: Ana" in fake.prompts[0] and "$25.50" in fake.prompts[0]
    assert "Ben" not in fake.prompts[0] and "300.00" not in fake.prompts[0]
    # "my ..." questions always get the asker's own record, even when nothing scores above the threshold
    text, tag = chat.answer(s, "Is my account in good standing?", ana)
    assert tag.startswith("via RAG · your account") and "Your balance: Ana" in fake.prompts[-1], tag
    # ...and are not refused when the SU's report matches best, but the report is never shown
    text, tag = chat.answer(s, "What is the revenue on my account?", ana)
    assert tag.startswith("via RAG · your account") and "revenue from" not in fake.prompts[-1], tag
    # a visitor asking about "my" account has none: plain LLM, which has no store records
    assert chat.answer(s, "Is my account in good standing?", None)[1] == "LLM · fake-chat"


def test_catalog_question():
    s, *_ = fresh()
    fake = FakeOllama()
    text, tag = chat.answer(s, "Who wrote Dracula?", None)
    assert tag == "via RAG · catalog" and '"Dracula" by Bram Stoker' in fake.prompts[0]


def test_embeddings_are_cached():
    s, *_ = fresh()
    fake = FakeOllama()
    chat.answer(s, "When is the help desk open?", None)
    first = len(fake.embedded)
    assert first > 5 and os.path.exists(chat.cache_path(s))
    fake.embedded.clear()
    chat.answer(s, "When is the help desk open?", None)
    assert len(fake.embedded) == 1  # only the question
    with open(s.path("store_info/hours.txt"), "a") as f:
        f.write("\nThe help desk is also open on Sunday from 12 pm to 2 pm.\n")
    fake.embedded.clear()
    chat.answer(s, "When is the help desk open?", None)
    assert len(fake.embedded) == 2  # the changed chunk and the question
    assert "Sunday from 12 pm" in fake.prompts[-1]


def test_works_without_embedding_model_or_ollama():
    s, *_ = fresh()
    fake = FakeOllama(embed_ok=False)
    text, tag = chat.answer(s, "What are the help desk hours?", None)
    assert tag.startswith("via RAG · hours.txt") and tag.endswith("(keyword match)"), tag
    offline = FakeOllama(embed_ok=False, chat_ok=False)  # Ollama not running at all
    text, tag = chat.answer(s, "What are the help desk hours?", None)
    assert "9 am to 6 pm" in text and "Ollama is offline" in tag
    assert "not running" in raises(chat.answer, s, "What is the capital of France?", None)
    assert len(fake.prompts) == 1 and not offline.prompts


def test_ask_the_book():
    s, ana, _, _ = fresh()
    fake = FakeOllama()
    dracula = s.books[3]
    assert "not available" in raises(askbook.answer, s, dracula, "Who is Harker?", None, {})
    os.makedirs(s.path("texts"))
    filler = "\n\n".join(f"Paragraph {i} is about the weather and the long road east." for i in range(60))
    with open(s.path("texts/b0004.txt"), "w") as f:
        f.write(filler + "\n\nJonathan Harker travelled to the castle of the Count.\n\n" + filler)
    dracula["text_path"] = "texts/b0004.txt"

    session = {}
    text, tag = askbook.answer(s, dracula, "Where did Harker go?", None, session)
    assert tag == 'via RAG · text of "Dracula"' and "Jonathan Harker travelled" in fake.prompts[-1]
    assert askbook.questions_left(None, session) == 2
    askbook.answer(s, dracula, "Who is Harker?", None, session)
    askbook.answer(s, dracula, "Tell me about the castle", None, session)
    assert "Visitors can ask 3" in raises(askbook.answer, s, dracula, "One more?", None, session)
    for _ in range(5):  # logged-in customers are unlimited
        askbook.answer(s, dracula, "Who is Harker?", ana, session)
    assert askbook.questions_left(ana, session) is None
    assert raises(askbook.answer, s, dracula, " ", ana, session) == "Type a question first"
    assert os.path.exists(s.path("rag_cache/book_b0004.json"))

    FakeOllama(chat_ok=False)
    text, tag = askbook.answer(s, dracula, "Where did Harker go?", ana, session)
    assert "Jonathan Harker travelled" in text and "Ollama is offline" in tag


def test_gutenberg_license_is_stripped():
    spec = importlib.util.spec_from_file_location("fetch", os.path.join(REPO, "scripts", "fetch_gutenberg.py"))
    fetch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetch)
    raw = ("The Project Gutenberg eBook\r\n*** START OF THE PROJECT GUTENBERG EBOOK DRACULA ***\r\n\r\n"
           "Produced by Some Volunteers\r\n\r\nCHAPTER I\r\nIt was dark.\r\n\r\n"
           "*** END OF THE PROJECT GUTENBERG EBOOK DRACULA ***\r\nLicense text")
    assert fetch.strip_license(raw) == "CHAPTER I\nIt was dark.\n"
    assert fetch.strip_license("Just a book.") == "Just a book.\n"


class FakeOllamaServer(BaseHTTPRequestHandler):
    batches = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["model"] == "missing":
            return self.reply(404, {"error": 'model "missing" not found, try pulling it first'})
        if self.path == "/api/embed":
            FakeOllamaServer.batches.append(len(body["input"]))
            return self.reply(200, {"embeddings": [[0.1, 0.2]] * len(body["input"])})
        if self.path == "/api/chat":
            assert body["stream"] is False and body["messages"][0]["role"] == "system"
            return self.reply(200, {"message": {"role": "assistant", "content": "  Hello there. "}})
        self.reply(404, {"error": "unknown endpoint"})

    def reply(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


def test_ollama_http_client():
    llm.embed, llm.chat = REAL_EMBED, REAL_CHAT
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    old = os.environ.get("OLLAMA_HOST")
    try:
        os.environ["OLLAMA_HOST"] = f"127.0.0.1:{server.server_port}"
        assert llm.chat("system", "hi") == "Hello there."
        assert len(llm.embed([f"t{i}" for i in range(130)])) == 130 and FakeOllamaServer.batches == [64, 64, 2]
        try:
            llm.embed(["x"], model="missing")
            raise AssertionError("expected Unavailable")
        except Unavailable as e:
            assert "ollama pull missing" in str(e)
        os.environ["OLLAMA_HOST"] = "0.0.0.0:11434"
        assert llm.host() == "http://127.0.0.1:11434"
    finally:
        server.shutdown()
        server.server_close()
    os.environ["OLLAMA_HOST"] = f"127.0.0.1:{server.server_port}"  # nothing listens there now
    try:
        llm.chat("system", "hi")
        raise AssertionError("expected Unavailable")
    except Unavailable as e:
        assert "not running" in str(e)
    finally:
        if old is None:
            os.environ.pop("OLLAMA_HOST", None)
        else:
            os.environ["OLLAMA_HOST"] = old


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
