"""Download the full text of catalog books from Project Gutenberg, for Ask-the-Book (UC-11).

The 8 demo books' texts are already in data/texts/. Use this for a book the SU adds later, from the repo root:

    python3 scripts/fetch_gutenberg.py b0009=1661      # book_id=Gutenberg ebook number

It saves data/texts/<book_id>.txt and sets the book's text_path in data/books.json. With no arguments it
re-downloads the demo books. Gutenberg sometimes refuses scripts (HTTP 503); try again later.

The ebook number is in the book's Gutenberg URL, e.g. gutenberg.org/ebooks/1342 is Pride and Prejudice.
"""
import os
import sys
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from novelty.store import Store  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
URL = "https://www.gutenberg.org/cache/epub/{n}/pg{n}.txt"
EBOOKS = {"Pride and Prejudice": 1342, "Frankenstein": 84, "Moby-Dick": 2701, "Dracula": 345, "Emma": 158,
          "Treasure Island": 120, "The Time Machine": 35, "A Study in Scarlet": 244}


def strip_license(text):
    """Keep only the book: drop Project Gutenberg's header, footer and volunteer credits."""
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    start, end = text.find("*** START OF"), text.find("*** END OF")
    if start != -1:
        text = text[text.find("\n", start) + 1:]
        end = text.find("*** END OF")
    text = (text[:end] if end != -1 else text).strip()
    if text.startswith("Produced by"):  # e.g. "Produced by Chuck Greif and the Online Distributed..."
        text = text.split("\n\n", 1)[-1].strip()
    return text + "\n"


def main(args):
    store = Store(DATA_DIR)
    wanted = {b["book_id"]: EBOOKS[b["title"]] for b in store.books if b["title"] in EBOOKS}
    for arg in args:
        book_id, _, number = arg.partition("=")
        if not number.isdigit():
            sys.exit(f"Expected book_id=ebook_number, got {arg!r}")
        wanted[book_id] = int(number)
    os.makedirs(os.path.join(DATA_DIR, "texts"), exist_ok=True)
    for book in store.books:
        n = wanted.get(book["book_id"])
        if n is None:
            continue
        req = urllib.request.Request(URL.format(n=n), headers={"User-Agent": "Novelty CSC32200 class project"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                text = strip_license(r.read().decode("utf-8", errors="replace"))
        except OSError as e:
            print(f"skipped {book['title']}: {e}")
            continue
        book["text_path"] = f"texts/{book['book_id']}.txt"
        with open(os.path.join(DATA_DIR, book["text_path"]), "w", encoding="utf-8") as f:
            f.write(text)
        print(f"saved {book['title']}  ({len(text) // 1000} KB)")
    store.save("books")


if __name__ == "__main__":
    main(sys.argv[1:])
