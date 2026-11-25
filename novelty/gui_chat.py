"""Chat screen (UC-10) and the Ask-the-Book box on the book page (UC-11).

Ollama can take several seconds to answer, so the core call runs on a worker thread and the window keeps
responding. Tk widgets are only touched on the main thread: the worker leaves its result in a queue that the
main thread checks every 150 ms with after().
"""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .core import askbook, chat
from .errors import NoveltyError


def session(app):
    """State for whoever is using the app now. Logging in or out starts a fresh one, so nobody sees the
    previous person's chat (an SU's finance answers, say) or inherits their Ask-the-Book count."""
    who = app.user["user_id"] if app.user else None
    if app.ai_session is None or app.ai_session["who"] != who:
        app.ai_session = {"who": who, "chat": [], "busy": False, "refresh": None, "askbook_used": 0}
    return app.ai_session


def in_background(app, fn, args, done):
    """Run fn(*args) on a worker thread, then call done(result, error_text) on the Tk thread."""
    results = queue.Queue()

    def work():
        try:
            results.put((fn(*args), None))
        except NoveltyError as e:
            results.put((None, str(e)))
        except Exception as e:  # SR-07: report it, never crash the window
            results.put((None, f"Something went wrong: {e}"))

    def poll():
        try:
            result, error = results.get_nowait()
        except queue.Empty:
            app.after(150, poll)
            return
        done(result, error)

    threading.Thread(target=work, daemon=True).start()
    app.after(150, poll)


def chat_screen(app):
    s = session(app)
    role = app.role()
    app.heading("Chat with Novelty", {
        "VS": "Ask about the store, our books, or anything else.",
        "SU": "Ask about the store, the books, sales and finances, or anything else.",
    }.get(role, "Ask about the store, our books, your account, or anything else."))

    frame = ttk.Frame(app.body)
    frame.pack(fill="both", expand=True)
    log = tk.Text(frame, wrap="word", height=16, padx=10, pady=8, relief="flat", borderwidth=0,
                  highlightthickness=1, highlightbackground="gray75", cursor="arrow",
                  font="TkDefaultFont")  # same font as the rest of the app (Text defaults to a typewriter font)
    bar = ttk.Scrollbar(frame, orient="vertical", command=log.yview)
    log.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    log.pack(side="left", fill="both", expand=True)
    log.tag_configure("you", font=("TkDefaultFont", 11, "bold"), spacing1=12)
    log.tag_configure("bot", spacing1=4)
    log.tag_configure("source", foreground="gray45", font=("TkDefaultFont", 9, "italic"), spacing3=4)
    log.tag_configure("error", foreground="firebrick", spacing1=4)

    row = ttk.Frame(app.body)
    row.pack(fill="x", pady=(8, 0))
    question = tk.StringVar()
    entry = ttk.Entry(row, textvariable=question)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
    send = ttk.Button(row, text="Send", command=lambda: ask())
    send.pack(side="left")
    ttk.Label(app.body, text='"via RAG" = answered from the store\'s own files and records.   '
                             '"LLM" = answered by the AI model on its own.', style="Sub.TLabel").pack(anchor="w")

    examples = {"VS": "“When is the help desk open?”  “Who wrote Dracula?”  “How do I become a VIP?”",
                "SU": "“How much revenue have we made?”  “Which books are low on stock?”  "
                      "“When is the help desk open?”"}

    def render():
        log.configure(state="normal")
        log.delete("1.0", "end")
        if not s["chat"]:
            log.insert("end", "Try asking: " + examples.get(
                role, "“What is my balance?”  “Who wrote Dracula?”  “How do I become a VIP?”") + "\n", "source")
        for kind, text, source in s["chat"]:
            if kind == "you":
                log.insert("end", f"You: {text}\n", "you")
            elif kind == "bot":
                log.insert("end", text + "\n", "bot")
                log.insert("end", f"[{source}]\n", "source")
            else:
                log.insert("end", text + "\n", "error")
        if s["busy"]:
            log.insert("end", "Novelty is thinking…\n", "source")
        log.configure(state="disabled")
        log.see("end")
        send.state(["disabled"] if s["busy"] else ["!disabled"])

    def refresh():
        if log.winfo_exists():  # the person may have moved to another screen meanwhile
            render()

    def ask(*_):
        text = question.get().strip()
        if not text or s["busy"]:
            return
        question.set("")
        s["chat"].append(("you", text, ""))
        s["busy"] = True

        def done(result, error):
            s["busy"] = False
            s["chat"].append(("bot", result[0], result[1]) if result else ("error", error, ""))
            if s["refresh"]:
                s["refresh"]()

        in_background(app, chat.answer, (app.store, text, app.user), done)
        render()

    s["refresh"] = refresh
    app.bind("<Return>", ask)
    entry.focus_set()
    render()


def ask_book_box(app, parent, book):
    box = ttk.LabelFrame(parent, text="Ask-the-Book", padding=8)
    box.pack(fill="x", pady=(8, 0))
    if not askbook.has_text(app.store, book):  # UC-11: tell the user the text is missing
        ttk.Label(box, text="The full text of this book is not available yet, so it can't answer questions.",
                  style="Sub.TLabel").pack(anchor="w")
        return
    s = session(app)
    row = ttk.Frame(box)
    row.pack(fill="x")
    question = tk.StringVar()
    entry = ttk.Entry(row, textvariable=question)
    entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
    button = ttk.Button(row, text="Ask the book", command=lambda: ask())
    button.pack(side="left")
    out = ttk.Label(box, text="", wraplength=640, justify="left")
    out.pack(anchor="w", pady=(6, 0))
    note = ttk.Label(box, text="", style="Sub.TLabel")
    note.pack(anchor="w")

    def limit_note():
        left = askbook.questions_left(app.user, s)
        if left is None:
            return 'Ask anything about this book, e.g. "Who is the main character?"'
        if left == 0:
            button.state(["disabled"])
            return "You have used your 3 free questions. Register or log in to ask as many as you like."
        return f"Visitors can try {askbook.VISITOR_LIMIT} questions: {left} left. Log in to ask as many as you like."

    def ask(*_):
        text = question.get().strip()
        if not text or button.instate(["disabled"]):
            return
        button.state(["disabled"])
        out.configure(text=f"Q: {text}\nReading the book… (the first question about a book takes longer)")
        note.configure(text="")

        def done(result, error):
            if not out.winfo_exists():
                return
            button.state(["!disabled"])
            out.configure(text=f"Q: {text}\n" + (f"A: {result[0]}" if result else error))
            note.configure(text=(f"[{result[1]}]   " if result else "") + limit_note())

        in_background(app, askbook.answer, (app.store, book, text, app.user, s), done)

    entry.bind("<Return>", ask)
    note.configure(text=limit_note())
