# Novelty — Software Design (v0.1)

Companion to `Novelty-SRS-v1.0`. One Python process, one desktop window, local files. No server, no database, no web.

## 1. Decisions that shrink the build

The SRS leaves these open or asks for something heavier than needed. Defaults below; change the one line in the code if the team disagrees.

| Topic | SRS says | We do | Why |
|---|---|---|---|
| GUI toolkit | PyQt6 *or* CustomTkinter | **plain `tkinter`** | Ships with Python, zero installs. Swap to CustomTkinter later if looks matter; the widgets have the same names. |
| Face ID | YOLO detect + a YOLO *classifier trained per user* | **YOLO detects the face, OpenCV LBPH identifies it** | Training a YOLO classifier at registration takes minutes and a GPU helps. LBPH trains in <1 s on a laptop from ~10 crops. Still "a simple YOLO-based procedure" per the constraint. |
| Voice ID | MFCC + classifier | MFCC (librosa) + **sklearn KNN** | Smallest classifier that works with 3–5 samples per user. |
| Picture search | "picture of a cover or figure" | **OpenCV ORB feature match** against stored covers, return top 3 by match count | No extra model, no embeddings. Works for photos of covers; weak on arbitrary illustrations — accepted. |
| RAG | "finds related text in local files" | Ollama `nomic-embed-text` + **plain-Python cosine similarity** over chunks cached in `data/rag_cache/` (keyword overlap if the embedding model is missing) | No vector DB, no numpy. A few hundred chunks search in milliseconds. |
| Recommendations | "based on browsing and purchase history" | Top-rated books in the **categories the user bought from**; fallback = top `copies_sold` | Needs no browsing log. Appendix A has no history file; we don't add one. |
| Rating weight | "greater weight to verified purchasers" | purchaser = 2, other = 1 | Any number works; pick one. |
| Overdraft purchase | "$1 fine, negative → suspended" | Purchase is **rejected**, $1 fine is charged; if balance < 0 the account is suspended | Spec doesn't say the book is delivered; not delivering is the safe reading. |
| Visitor Ask-the-Book | visitors "try", RC "unlimited" | Visitors get **3 questions per session** | Simplest cap that makes the distinction visible. |
| SU finance questions | "only SU gets finance answers" | RAG docs carry a `roles` tag; retrieval drops chunks the current role can't see | One filter, satisfies SR-01/SR-03. |
| Concurrency | "one person at a time" | No locking. Files rewritten whole with `tmp + os.replace` | Atomic write covers SR-06/SR-09. |

Not built, on purpose: user browsing history, a vector database, PyQt6, any web/API layer, password login (biometrics only, as specified), multiple SU accounts.

**If the project ever goes web** (the spec currently forbids it): replace `gui.py` with a Flask app + HTML templates on `localhost`. `core/`, `store.py`, `data/` and the tests do not change — that is why `core` never imports tkinter.

## 2. Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│  gui.py  (tkinter)   App window: nav buttons left, one screen right    │
│                      App.user is the session (None = visitor)          │
│                                                                        │
│  Nav ──▶ Home │ Browse+Search │ Book │ Register │ Login                 │
│          Account │ Chat │ Admin                                         │
│         every screen reads App.user to decide what to show             │
├──────────────────────────────▲────────────────────────────────────────┤
│  core/  plain Python, no GUI │ imports                                 │
│                                                                        │
│  auth.py      register(), login_face(), login_voice()                  │
│  catalog.py   browse(), search_text(), search_image(), add_book(),     │
│               recommend(), order_lists()                               │
│  accounts.py  deposit(), purchase(), reopen(), _promote(), _suspend()  │
│  reviews.py   rate(), filter_taboo(), add/remove_taboo()               │
│  chat.py      answer(question, user) → RAG or plain LLM                │
│  askbook.py   answer(book, question, user, session)                    │
│  rag.py llm.py  shared retrieval; tiny Ollama HTTP client              │
├──────────────────────────────▲────────────────────────────────────────┤
│  store.py    load()/save() per file; atomic writes; next_id("u")       │
├──────────────────────────────▲────────────────────────────────────────┤
│  data/                                                                 │
│  users.json  books.json  ratings.json  transactions.csv                │
│  taboo_words.txt  rag_cache/  store_info/*.txt  covers/  texts/        │
│  biometrics/<uid>/face/*.jpg  biometrics/<uid>/voice/*.wav             │
└───────────────────────────────────────────────────────────────────────┘
          │ biometrics (cv2, ultralytics, librosa, sklearn)
          │ ollama (HTTP on localhost:11434 — chat + embeddings)
```

Rules that keep it simple:

- **Dependencies point down only.** `gui` → `core` → `store` → files. `core` never imports tkinter; `store` never knows what a user is.
- **One `Store` object owns the files.** Every service takes it in its constructor. Tests pass a `Store(tmp_path)`.
- **Services return plain values or raise `NoveltyError(msg)`.** The GUI catches that one exception type and shows the message (SR-07, SR-11).
- **Hardware/Ollama failures raise `Unavailable(msg)`**, a subclass of `NoveltyError`. The feature shows the message; the rest of the app keeps working (SR-08).

## 3. Modules

### `store.py`
- `Store(data_dir)`; `users`, `books`, `ratings` are lists of dicts loaded at start and saved with `save("users")`.
- `append_transaction(user_id, type, book_id, amount)` appends one CSV row.
- `taboo()` / `save_taboo(set)`.
- `next_id(prefix)` → `"u007"`.
- Writes go to `name.tmp` then `os.replace`. Missing file ⇒ empty list, logged, not a crash.

### `core/auth.py`
- `register(name, face_frames | None, voice_clips | None)` — needs at least one modality; saves crops/wavs under `biometrics/<uid>/`, retrains LBPH and the voice KNN, creates the RC record with balance 0.
- `login_face(frame)` → user or `NoveltyError("not recognized")`; suspended ⇒ `NoveltyError("account suspended")`.
- `login_voice(clip)` — same contract.
- Face pipeline: `yolov8n-face` (or general YOLO + "person" crop → Haar face) → grayscale 100×100 → `cv2.face.LBPHFaceRecognizer`. Confidence threshold is a constant.
- Voice pipeline: `librosa.feature.mfcc` mean+std → 40-dim vector → `KNeighborsClassifier(k=1)` with distance cutoff.
- SU is seeded by `scripts/seed.py` (enrols the admin once at setup).

### `core/catalog.py`
- `browse(category=None, author=None, since=None)`.
- `search_text(q)` — case-insensitive substring over title/author/category.
- `search_image(path)` — ORB descriptors of the query vs. a cache of each cover's descriptors; return books with ≥ N good matches, best first. Invalid image ⇒ `NoveltyError`.
- `recommend(user)` — see §1.
- `order_lists()` — `(to_order, no_order)` from weighted averages, books with > 3 ratings only.
- `add_book(fields)` — validate, `next_id("b")`, append, save.

### `core/accounts.py`
- `deposit(user, amount)` — amount > 0 else error; update, save, CSV row.
- `purchase(user, book)`:
  1. role not in (RC, VC) ⇒ error; status suspended ⇒ error; stock 0 ⇒ error.
  2. price × 0.9 if VC.
  3. if price > balance: balance −= 1, CSV `fine`, suspend if balance < 0, raise error "insufficient funds, $1 fine".
  4. else balance −= price, stock −= 1, copies_sold += 1, CSV `purchase`.
  5. RC with > 3 purchases **or** > $200 lifetime spend ⇒ role = VC.
- `reopen(user)` — SU only; balance > 0 ⇒ status active else error.

### `core/reviews.py`
- `filter_taboo(text)` → `(cleaned, count)`; whole-word, case-insensitive, replaced with `*` × len.
- `rate(book, user_or_None, stars, comment)`:
  - stars ∉ 1..5 ⇒ error.
  - count > 3 ⇒ blocked: `warnings += 1`; RC with warnings > 2 ⇒ suspended; VC ⇒ demoted to RC. Raise error so the GUI tells them.
  - else save rating with cleaned comment.
- `weighted_avg(book)` — purchaser weight 2.
- `add_taboo(w)` / `remove_taboo(w)` — strip, lowercase, reject empty/duplicate/missing.

### `core/llm.py`
- `chat(system, prompt)` and `embed(texts)` over Ollama's HTTP API with `urllib` (no `ollama` package). Any failure ⇒ `Unavailable` with a fix the user can act on ("run `ollama pull llama3.2`", "start Ollama").
- Models: `llama3.2` and `nomic-embed-text`; override with `NOVELTY_CHAT_MODEL` / `NOVELTY_EMBED_MODEL`. Host from `OLLAMA_HOST`.

### `core/rag.py`
- A chunk is `{source, text, roles, owner}`. `split()` packs paragraphs into ≤ 500-char chunks (1000 for books).
- `search(question, chunks, cache)` → `(method, [(score, chunk)])`. Embeddings are cached in `data/rag_cache/*.json` keyed by chunk text, so the index rebuilds itself: editing a store file re-embeds only what changed, no build script. If the embedding model is unavailable, `method = "keyword"` (weighted keyword overlap).
- `THRESHOLD = {"embedding": 0.6, "keyword": 0.5}`: tune with `python3 scripts/chat_cli.py --debug`.

### `core/chat.py`
- `answer(question, user)` → `(text, tag)`:
  1. build chunks: `store_info/*.txt` (everyone; files named `finance*`/`admin*` are SU only), the **catalog** (live from books.json), a **finance report** (SU only, live from transactions.csv), and **"your account"** (balance, purchases, membership: only the logged-in RC/VC it describes).
  2. top 3 chunks the user may see with score ≥ threshold ⇒ prompt = chunks + question, tag `"via RAG · hours.txt"`.
  3. checked first: the single best match is a chunk this user may not see ⇒ `"Sorry, that information is only available to the store administrator."`, tag `"restricted"`. The model never sees hidden chunks (SR-03).
  4. nothing matches ⇒ question alone, tag `"LLM · llama3.2"`; its system prompt says it cannot see store records.
  - Questions about yourself ("my", "I", "me") always get the asker's own account chunks and are never refused.
  5. Ollama down: a RAG hit still shows the matching store text; an LLM question raises `Unavailable` (SR-08).

### `core/askbook.py`
- Same retrieval over one book's `text_path` (1000-char chunks, cached in `data/rag_cache/book_<id>.json`); always answers from the 4 best passages. No text file ⇒ `NoveltyError`. Visitors get 3 questions per session (`session` dict kept by the GUI); logged-in users are unlimited.
- `scripts/fetch_gutenberg.py` downloads the demo books' text from Project Gutenberg and sets `text_path`.

### `gui_chat.py`
- Chat screen and the Ask-the-Book box on the book page. Calls run on a worker thread; the result comes back through a queue polled with `after()`, so the window never freezes. Chat history lives in `App.ai_session` and is cleared when the user changes (an SU's finance answers are not left on screen after logout).

### `gui.py`
- `App(tk.Tk)` holds `store` and `user`. `show(screen, *args)` wipes both frames, redraws the nav for the current role, then calls the screen method, so a login or demotion shows immediately.
- One method per screen. `run(fn, *args, then=..., ok=...)` calls a core function, shows a `NoveltyError` in a message box or a confirmation, and redraws.
- Camera preview (later): OpenCV frame → PIL → `PhotoImage` every 30 ms on `after()`. Recording: `sounddevice.rec` 3 s.
- Nav items by role:

| Screen | VS | RC/VC | SU |
|---|---|---|---|
| Home (3 recs) | ✓ | ✓ | ✓ |
| Browse / Search | ✓ | ✓ | ✓ |
| Book detail (rate, comment, ask-the-book) | ✓ | ✓ | ✓ (no ask-the-book needed; keep it, costs nothing) |
| Register | ✓ | | |
| Login / Logout | ✓ | ✓ | ✓ |
| Account (balance, deposit, buy history) | | ✓ | |
| Chat | ✓ | ✓ | ✓ |
| Admin (add book, taboo words, reopen, order lists) | | | ✓ |

## 4. Three flows worth drawing

**Login (UC-06)**
```
LoginScreen ─frame──▶ auth.login_face ─▶ yolo.detect ─▶ crop ─▶ lbph.predict
                                     ◀── user dict or NoveltyError
            session.user = user ─▶ app.refresh_sidebar()
```

**Purchase (UC-08)**
```
BookScreen.buy ─▶ accounts.purchase(user, book)
                      ├─ ok:    users.json, books.json, transactions.csv  → "Bought for $X"
                      └─ short: users.json (−$1, maybe suspended), transactions.csv(fine) → error text
```

**Chat (UC-10)**
```
ChatScreen ─thread─▶ chat.answer(q, user)
               ├─ embed(q) ─▶ cosine vs all chunks (cached vectors)
               ├─ visible hit ─▶ ollama.chat(context + q)  → (text, "via RAG · hours.txt")
               ├─ hidden hit  ─▶ no model call             → (refusal, "restricted")
               └─ miss        ─▶ ollama.chat(q)            → (text, "LLM · llama3.2")
```

## 5. Traceability

| UC | Module.function | Files touched |
|---|---|---|
| 01 | catalog.recommend | books, ratings, transactions |
| 02 | catalog.browse | books |
| 03 | catalog.search_text / search_image | books, covers |
| 04 | catalog + reviews.weighted_avg | books, ratings |
| 05 | auth.register | users, biometrics/ |
| 06 | auth.login_* / logout | users |
| 07 | accounts.deposit | users, transactions |
| 08 | accounts.purchase | users, books, transactions |
| 09 | reviews.rate | ratings, taboo_words, users |
| 10 | chat.answer | store_info/, books, ratings, users, transactions, rag_cache/ |
| 11 | askbook.answer | texts/, rag_cache/ |
| 12 | catalog.add_book | books |
| 13 | reviews.add_taboo / remove_taboo | taboo_words |
| 14 | accounts.reopen | users |
| 15 | catalog.order_lists | books, ratings |

## 6. Repo layout

```
novelty/
  gui.py            entry point: python3 -m novelty.gui
  store.py
  gui_chat.py       Chat screen + Ask-the-Book box
  errors.py         NoveltyError, Unavailable
  core/  accounts.py reviews.py catalog.py chat.py askbook.py rag.py llm.py   + later: auth.py
data/               demo files are committed; `git checkout -- data` resets them
  store_info/       text the chatbot answers from (edit freely)
  rag_cache/        embedding cache, rebuilt automatically, not committed
scripts/            chat_cli.py (terminal chat), fetch_gutenberg.py
tests/              test_core.py, test_ai.py  (no GUI, no hardware, fake Ollama; plain asserts, no pytest needed)
requirements.txt    later: opencv-contrib-python ultralytics librosa sounddevice scikit-learn numpy pillow ollama
```

## 7. Build order

1. ✅ `store.py` + `errors.py` + `core/accounts.py` + `core/reviews.py` + `core/catalog.py` with tests — all the money/moderation rules, no hardware.
2. ✅ `gui.py`: Home/Browse/Book/Register/Login/Account/Admin against the committed data. **This is the barebones frontend.** Login is a dropdown of users and `register()` lives in `accounts.py` until step 3.
3. `auth.py` face, then voice; move `register()` there.
4. ✅ `chat.py` + `askbook.py` + `rag.py` + `llm.py`; the Chat screen and the Ask-the-Book box.
5. `search_image`.

## 8. Open questions for the team

- Does the SU need to be able to *buy*? Table 1 says no; the design follows that.
- After a VC is demoted for a warning, does their warning count reset? Design: no, it keeps counting toward suspension.
- "Browse by time": newest first, or filter by a date range? Design: filter `since` a date, newest first.
