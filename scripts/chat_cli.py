"""Chat with Novelty in the terminal, without the GUI. Handy for testing Ollama and tuning rag.THRESHOLD.

    python3 scripts/chat_cli.py                  # as a visitor
    python3 scripts/chat_cli.py --as Admin       # as a user from data/users.json (by name)
    python3 scripts/chat_cli.py --debug          # also print the retrieval scores

Type a question and press Enter. An empty line quits.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from novelty.core import chat, rag  # noqa: E402
from novelty.errors import NoveltyError  # noqa: E402
from novelty.store import Store  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--as", dest="name", help="log in as this user (name from users.json)")
    p.add_argument("--debug", action="store_true", help="show the top retrieval scores for each question")
    args = p.parse_args()
    store = Store(DATA_DIR)
    user = None
    if args.name:
        user = next((u for u in store.users if u["name"].lower() == args.name.lower()), None)
        if user is None:
            sys.exit(f"No user named {args.name}. Users: {', '.join(u['name'] for u in store.users)}")
    print(f"Chatting as {user['name'] + ' (' + user['role'] + ')' if user else 'a visitor'}. Empty line quits.")
    while True:
        try:
            q = input("\nyou> ").strip()
        except EOFError:
            break
        if not q:
            break
        if args.debug:
            method, scored = rag.search(q, chat.documents(store, user), chat.cache_path(store))
            print(f"  [{method}, threshold {rag.THRESHOLD[method]}]")
            for score, c in scored[:5]:
                seen = "" if chat.can_see(user, c) else "  (hidden from this user)"
                print(f"  {score:.3f}  {c['source']:<16} {c['text'][:60]!r}{seen}")
        try:
            text, tag = chat.answer(store, q, user)
        except NoveltyError as e:
            print(f"novelty> {e}")
            continue
        print(f"novelty> {text}\n         [{tag}]")


if __name__ == "__main__":
    main()
