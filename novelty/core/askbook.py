"""UC-11 Ask-the-Book: answer a question about one book from its own full text (books.json text_path).

The text is cut into ~1000 character chunks; their embeddings are cached in data/rag_cache/book_<id>.json,
so only the first question about a book is slow.
"""
import os

from ..errors import NoveltyError, Unavailable
from . import llm, rag

VISITOR_LIMIT = 3          # visitors "try" Ask the Book (SRS Table 1); logged in users are unlimited
TOP_K = 4                  # passages given to the model per question
CHUNK_SIZE, OVERLAP = 1000, 150


def has_text(store, book):
    return bool(book.get("text_path")) and os.path.isfile(store.path(book["text_path"]))


def questions_left(user, session):
    """None means unlimited. `session` is a dict the GUI keeps for the current visitor."""
    return None if user else max(VISITOR_LIMIT - session.get("askbook_used", 0), 0)


def answer(store, book, question, user, session):
    question = question.strip()
    if not question:
        raise NoveltyError("Type a question first")
    if questions_left(user, session) == 0:
        raise NoveltyError(f"Visitors can ask {VISITOR_LIMIT} questions. Register or log in to ask as many "
                           "as you like.")
    if not has_text(store, book):
        raise NoveltyError(f'Sorry, the text of "{book["title"]}" is not available, so this book cannot '
                           "answer questions yet.")
    try:
        with open(store.path(book["text_path"]), encoding="utf-8", errors="replace") as f:
            chunks = rag.make_chunks(book["title"], f.read(), size=CHUNK_SIZE, overlap=OVERLAP)
    except OSError:
        chunks = []
    if not chunks:
        raise NoveltyError(f'The text file of "{book["title"]}" is empty or unreadable.')

    cache = os.path.join(store.path("rag_cache"), f'book_{book["book_id"]}.json')
    method, scored = rag.search(question, chunks, cache)
    passages = [c["text"] for _, c in scored[:TOP_K]]
    tag = f'via RAG · text of "{book["title"]}"' + (" (keyword match)" if method == "keyword" else "")
    system = (f'You answer questions about the book "{book["title"]}" by {book["author"]}. Use only the '
              "passages below. Keep it short: one to four sentences. If the passages do not answer the "
              "question, say so.")
    try:
        reply = llm.chat(system, "Passages:\n\n" + "\n---\n".join(passages) + f"\n\nQuestion: {question}")
    except Unavailable:  # SR-08: still useful without the model
        reply, tag = passages[0], tag + " · Ollama is offline, showing the closest passage"
    if user is None:
        session["askbook_used"] = session.get("askbook_used", 0) + 1
    return reply, tag
