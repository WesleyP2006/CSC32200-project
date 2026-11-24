# CSC32200-project — Novelty

AI enabled desktop bookstore for CSC 32200. Python 3.9+, standard library only so far.

- Run the app: `python3 -m novelty.gui`
- Run the tests: `python3 tests/test_core.py` and `python3 tests/test_ai.py`
- Reset the demo data: `git checkout -- data`
- Design: [docs/DESIGN.md](docs/DESIGN.md)

Demo users (log-in dropdown): Ana (RC, $25.50), Ben (VC, $300), Admin (SU).

## AI features (chatbot and Ask-the-Book)

They need [Ollama](https://ollama.com) running on the same computer, with two free models:

```
ollama pull llama3.2           # answers questions (2 GB)
ollama pull nomic-embed-text   # finds the matching store text (300 MB)
```

- Ask-the-Book reads `data/texts/` (the 8 demo books from Project Gutenberg are included). For a book the SU adds: `python3 scripts/fetch_gutenberg.py b0009=<Gutenberg ebook number>`

- Try the chatbot without the GUI: `python3 scripts/chat_cli.py --as Admin --debug`
- What the chatbot knows: `data/store_info/*.txt` (edit them; files starting with `finance` are SU only), plus the live catalog, an SU-only finance report and the logged-in customer's own account.
- Without Ollama the rest of the app works as before; the chat shows what to start or install.
- Other models: `NOVELTY_CHAT_MODEL=mistral python3 -m novelty.gui`
