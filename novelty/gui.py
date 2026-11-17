"""Tkinter GUI with themed (ttk) widgets: nav on the left, one screen at a time on the right.

Run from the repo root:  python3 -m novelty.gui
"""
import os

os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")  # macOS system Tk prints a harmless warning otherwise

import tkinter as tk  # noqa: E402
from tkinter import messagebox, ttk  # noqa: E402

from .core import accounts, catalog, reviews  # noqa: E402
from .errors import NoveltyError  # noqa: E402
from .store import Store  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
NUMERIC = {"Price", "Amount", "Stock", "Rating", "Balance", "Warnings"}


def _num(text, cast):
    try:
        return cast(text)
    except ValueError:
        return -1  # core rejects negatives with a readable message


class App(tk.Tk):
    def __init__(self, store):
        super().__init__()
        self.title("Novelty Bookstore")
        self.geometry("980x660")
        self.minsize(820, 540)
        style = ttk.Style(self)
        style.configure("Heading.TLabel", font=("TkDefaultFont", 17, "bold"))
        style.configure("Section.TLabel", font=("TkDefaultFont", 13, "bold"))
        style.configure("Big.TLabel", font=("TkDefaultFont", 14, "bold"))
        style.configure("Sub.TLabel", foreground="gray40")
        self.store = store
        self.user = None  # None = visitor
        self.current = self.prev = None
        self.admin_tab = 0
        self.nav = ttk.Frame(self, padding=12)
        self.nav.pack(side="left", fill="y")
        ttk.Separator(self, orient="vertical").pack(side="left", fill="y")
        self.body = ttk.Frame(self, padding=16)
        self.body.pack(side="left", fill="both", expand=True)
        self.show(self.home)

    # ---- plumbing ----
    def role(self):
        return self.user["role"] if self.user else "VS"

    def show(self, screen, *args):
        if self.current and self.current[0] is not screen:
            self.prev = self.current
        self.current = (screen, args)
        self.unbind("<Return>")
        for w in self.nav.winfo_children() + self.body.winfo_children():
            w.destroy()
        ttk.Label(self.nav, text="Novelty", style="Heading.TLabel").pack(pady=(0, 14))
        items = [("Home", self.home), ("Browse & search", self.browse)]
        if self.user is None:
            items += [("Register", self.register), ("Log in", self.login)]
        if self.role() in ("RC", "VC"):
            items.append(("My account", self.account))
        if self.role() == "SU":
            items.append(("Administration", self.admin))
        if self.user:
            items.append(("Log out", self.logout))
        for text, fn in items:
            ttk.Button(self.nav, text=text, width=16, command=lambda f=fn: self.show(f)).pack(pady=3)
        if self.user is None:
            who = "Browsing as a visitor"
        else:
            who = f'{self.user["name"]} · {self.user["role"]}'
            if self.role() != "SU":
                who += f'\nBalance ${self.user["balance"]:.2f}'
        ttk.Label(self.nav, text=who, style="Sub.TLabel", justify="center").pack(side="bottom")
        screen(*args)

    def run(self, fn, *args, then, ok=None):
        """Call a core function: show its error, or confirm and redraw the screen."""
        try:
            fn(*args)
        except NoveltyError as e:
            messagebox.showerror("Novelty", str(e))
            return
        if ok:
            messagebox.showinfo("Novelty", ok)
        self.show(*then)

    def heading(self, text, sub=None):
        ttk.Label(self.body, text=text, style="Heading.TLabel").pack(anchor="w")
        ttk.Label(self.body, text=sub or "", style="Sub.TLabel").pack(anchor="w", pady=(0, 10))

    def form(self, parent, fields):
        """fields: [(caption, default text or list of choices)]. Returns {caption: StringVar}."""
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=4)
        out = {}
        for i, (caption, default) in enumerate(fields):
            ttk.Label(grid, text=caption).grid(row=i, column=0, sticky="w", padx=(0, 8), pady=2)
            if isinstance(default, list):
                var = tk.StringVar(value=default[0] if default else "")
                ttk.Combobox(grid, textvariable=var, values=default, state="readonly", width=28).grid(
                    row=i, column=1, sticky="w", pady=2)
            else:
                var = tk.StringVar(value=default)
                ttk.Entry(grid, textvariable=var, width=30).grid(row=i, column=1, sticky="w", pady=2)
            out[caption] = var
        return out

    def table(self, parent, columns, rows, on_open=None, height=10):
        """columns: [(heading, width)]; rows: [(iid, values)]. Double-click / Enter calls on_open(iid)."""
        tree = ttk.Treeview(parent, columns=[c for c, _ in columns], show="headings", height=height)
        for c, w in columns:
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="e" if c in NUMERIC else "w")
        for iid, values in rows:
            tree.insert("", "end", iid=iid, values=values)
        tree.pack(fill="both", expand=True, pady=4)
        if on_open:
            def opener(_event):
                if tree.selection():
                    on_open(tree.selection()[0])
            tree.bind("<Double-1>", opener)
            tree.bind("<Return>", opener)
        return tree

    def book_table(self, parent, books):
        if not books:
            ttk.Label(parent, text="No books found.", style="Sub.TLabel").pack(anchor="w")
            return
        by_id = {b["book_id"]: b for b in books}
        rows = []
        for b in books:
            avg, n = reviews.weighted_avg(self.store, b["book_id"])
            rows.append((b["book_id"], (b["title"], b["author"], b["category"], f'${b["price"]:.2f}',
                                        f"{avg} ({n})" if n else "—", b["stock"] or "out")))
        self.table(parent, [("Title", 270), ("Author", 170), ("Category", 110), ("Price", 60),
                            ("Rating", 70), ("Stock", 50)],
                   rows, on_open=lambda i: self.show(self.book, by_id[i]))
        ttk.Label(parent, text="Double-click a book to open it.", style="Sub.TLabel").pack(anchor="w")

    # ---- screens ----
    def home(self):
        if self.role() in ("RC", "VC"):
            self.heading(f'Welcome back, {self.user["name"]}', "Recommended for you, based on what you have bought")
        else:
            self.heading("Welcome to Novelty", "Popular right now")
        self.book_table(self.body, catalog.recommend(self.store, self.user))
        if self.user is None:
            ttk.Label(self.body, text="Register or log in to buy books and get personal recommendations.").pack(
                anchor="w", pady=8)

    def browse(self):
        self.heading("Browse & search", "Type a keyword, or leave it empty and filter by category, author or date")
        cats = ["Any"] + sorted({b["category"] for b in self.store.books})
        f = self.form(self.body, [("Keyword", ""), ("Category", cats), ("Author", ""), ("Added since (YYYY-MM-DD)", "")])
        results = ttk.Frame(self.body)

        def go(*_):
            for w in results.winfo_children():
                w.destroy()
            q = f["Keyword"].get().strip()
            cat = "" if f["Category"].get() == "Any" else f["Category"].get()
            books = (catalog.search_text(self.store, q) if q
                     else catalog.browse(self.store, cat, f["Author"].get(), f["Added since (YYYY-MM-DD)"].get()))
            ttk.Label(results, text=f"{len(books)} book(s)").pack(anchor="w")
            self.book_table(results, books)

        ttk.Button(self.body, text="Search", command=go).pack(anchor="w", pady=4)
        self.bind("<Return>", go)
        results.pack(fill="both", expand=True)
        go()

    def book(self, b):
        if self.prev:
            ttk.Button(self.body, text="← Back", command=lambda: self.show(self.prev[0], *self.prev[1])).pack(anchor="w")
        avg, n = reviews.weighted_avg(self.store, b["book_id"])
        self.heading(b["title"], f'{b["author"]} · {b["category"]} · added {b["date_added"]}')
        info = ttk.Frame(self.body)
        info.pack(fill="x")
        ttk.Label(info, text=f'${b["price"]:.2f}', style="Big.TLabel").pack(side="left")
        rating = f"Rating {avg} from {n} review(s)" if n else "No reviews yet"
        stock = f'In stock: {b["stock"]}' if b["stock"] else "Out of stock"
        ttk.Label(info, text=f"     {rating}     ·     {stock}").pack(side="left")
        if self.role() in ("RC", "VC"):
            price = b["price"] * (0.9 if self.role() == "VC" else 1)
            text = f"Buy for ${price:.2f}" + ("  (VIP 10% off)" if self.role() == "VC" else "")
            ttk.Button(self.body, text=text, command=lambda: self.run(
                accounts.purchase, self.store, self.user, b, then=(self.book, b),
                ok=f'You bought "{b["title"]}".')).pack(anchor="w", pady=8)
        elif self.user is None:
            ttk.Label(self.body, text="Log in to buy this book.", style="Sub.TLabel").pack(anchor="w", pady=8)

        box = ttk.LabelFrame(self.body, text="Rate this book", padding=8)
        box.pack(fill="x", pady=8)
        f = self.form(box, [("Stars", ["5", "4", "3", "2", "1"]), ("Comment", "")])
        ttk.Button(box, text="Post review", command=lambda: self.run(
            reviews.rate, self.store, b, self.user, _num(f["Stars"].get(), int), f["Comment"].get(),
            then=(self.book, b), ok="Thanks for your review!")).pack(anchor="w")

        rs = [r for r in self.store.ratings if r["book_id"] == b["book_id"]]
        rev = ttk.LabelFrame(self.body, text=f"Reviews ({len(rs)})", padding=8)
        rev.pack(fill="both", expand=True)
        names = {u["user_id"]: u["name"] for u in self.store.users}
        for r in reversed(rs):
            who = names.get(r["user_id"], "Visitor") + ("  ✓ purchased" if r["verified"] else "")
            stars = "★" * r["stars"] + "☆" * (5 - r["stars"])
            ttk.Label(rev, text=f'{stars}  {who}  —  {r["comment"] or "(no comment)"}',
                      wraplength=640, justify="left").pack(anchor="w", pady=2)
        if not rs:
            ttk.Label(rev, text="Be the first to review this book.", style="Sub.TLabel").pack(anchor="w")

    def register(self):
        self.heading("Create an account", "Face and voice enrolment will be added here later; for now just a name")
        f = self.form(self.body, [("Your name", "")])
        ttk.Button(self.body, text="Register", command=lambda: self.run(
            accounts.register, self.store, f["Your name"].get(), then=(self.login,),
            ok="Account created! Pick yourself in the list to log in.")).pack(anchor="w")

    def login(self):
        # shortcut: a dropdown stands in for face/voice recognition, replace when auth.py exists
        self.heading("Log in", "Face and voice recognition come later; pick your account for now")
        by_label = {f'{u["name"]}  ({u["role"]})': u for u in self.store.users}
        f = self.form(self.body, [("Account", list(by_label))])

        def go(*_):
            u = by_label[f["Account"].get()]
            if u["status"] != "active":
                return messagebox.showerror("Novelty", "This account is suspended. Ask the administrator to reopen it.")
            self.user = u
            self.show(self.home)

        ttk.Button(self.body, text="Log in", command=go).pack(anchor="w")
        self.bind("<Return>", go)

    def logout(self):
        self.user = None
        self.show(self.home)

    def account(self):
        u = self.user
        kind = "VIP customer — 10% off everything" if u["role"] == "VC" else "Registered customer"
        self.heading("My account", f'{u["name"]} · {kind} · {u["warnings"]} warning(s)')
        ttk.Label(self.body, text=f'Balance: ${u["balance"]:.2f}', style="Big.TLabel").pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=8)
        amt = tk.StringVar()
        ttk.Label(row, text="Deposit $").pack(side="left")
        ttk.Entry(row, textvariable=amt, width=10).pack(side="left", padx=4)
        ttk.Button(row, text="Deposit", command=lambda: self.run(
            accounts.deposit, self.store, u, _num(amt.get(), float), then=(self.account,),
            ok="Deposit saved.")).pack(side="left")
        if u["role"] == "RC":
            ttk.Label(self.body, text="Become a VIP after more than 3 purchases or $200 spent.",
                      style="Sub.TLabel").pack(anchor="w")
        ttk.Label(self.body, text="History", style="Section.TLabel").pack(anchor="w", pady=(14, 0))
        titles = {b["book_id"]: b["title"] for b in self.store.books}
        rows = [(t["transaction_id"], (t["timestamp"].replace("T", "  "), t["type"],
                                       titles.get(t["book_id"], ""), f'${t["amount"]}'))
                for t in reversed(self.store.transactions(u["user_id"]))]
        if rows:
            self.table(self.body, [("When", 170), ("Type", 80), ("Book", 280), ("Amount", 80)], rows)
        else:
            ttk.Label(self.body, text="No transactions yet.", style="Sub.TLabel").pack(anchor="w")

    def admin(self):
        self.heading("Administration")
        tabs = ttk.Notebook(self.body)
        tabs.pack(fill="both", expand=True)
        for name, build in (("Add book", self.admin_books), ("Taboo words", self.admin_taboo),
                            ("Accounts", self.admin_accounts), ("Order lists", self.admin_orders)):
            page = ttk.Frame(tabs, padding=12)
            tabs.add(page, text=name)
            build(page)
        tabs.select(self.admin_tab)
        tabs.bind("<<NotebookTabChanged>>", lambda e: setattr(self, "admin_tab", tabs.index("current")))

    def admin_books(self, page):
        f = self.form(page, [("Title", ""), ("Author", ""), ("Category", ""), ("Price $", ""), ("Stock", "")])
        ttk.Button(page, text="Add book", command=lambda: self.run(
            catalog.add_book, self.store, f["Title"].get(), f["Author"].get(), f["Category"].get(),
            _num(f["Price $"].get(), float), _num(f["Stock"].get(), int),
            then=(self.admin,), ok="Book added to the catalog.")).pack(anchor="w", pady=6)

    def admin_taboo(self, page):
        ttk.Label(page, text="Comments with more than 3 of these words are blocked; fewer are starred out.",
                  style="Sub.TLabel").pack(anchor="w")
        words = sorted(self.store.taboo())
        lb = tk.Listbox(page, height=10, width=30)
        lb.insert("end", *words)
        lb.pack(anchor="w", pady=6)
        row = ttk.Frame(page)
        row.pack(anchor="w")
        var = tk.StringVar()
        ttk.Entry(row, textvariable=var, width=20).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Add word", command=lambda: self.run(
            reviews.add_taboo, self.store, var.get(), then=(self.admin,))).pack(side="left")

        def selected():
            return words[lb.curselection()[0]] if lb.curselection() else var.get()

        ttk.Button(row, text="Remove selected", command=lambda: self.run(
            reviews.remove_taboo, self.store, selected(), then=(self.admin,))).pack(side="left", padx=6)

    def admin_accounts(self, page):
        rows = [(u["user_id"], (u["name"], u["role"], f'${u["balance"]:.2f}', u["status"], u["warnings"]))
                for u in self.store.users]
        tree = self.table(page, [("Name", 160), ("Role", 60), ("Balance", 90), ("Status", 100), ("Warnings", 80)],
                          rows, height=8)
        ttk.Label(page, text="Select a suspended account. A deposit is optional, but the balance must be "
                             "positive to reopen.", style="Sub.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(anchor="w", pady=6)
        amt = tk.StringVar()
        ttk.Label(row, text="Deposit $").pack(side="left")
        ttk.Entry(row, textvariable=amt, width=10).pack(side="left", padx=4)

        def reopen():
            if not tree.selection():
                return messagebox.showerror("Novelty", "Select an account first.")
            u = next(u for u in self.store.users if u["user_id"] == tree.selection()[0])
            if u["status"] == "active":
                return messagebox.showerror("Novelty", f'{u["name"]} is not suspended.')
            self.run(accounts.reopen, self.store, u, _num(amt.get() or "0", float),
                     then=(self.admin,), ok=f'{u["name"]} can log in again.')

        ttk.Button(row, text="Reopen selected account", command=reopen).pack(side="left")

    def admin_orders(self, page):
        to_order, no_order = catalog.order_lists(self.store)
        cols = ttk.Frame(page)
        cols.pack(fill="both", expand=True)
        for title, books in (("To order  (average above 4, more than 3 reviews)", to_order),
                             ("Do not reorder  (average below 2, more than 3 reviews)", no_order)):
            box = ttk.LabelFrame(cols, text=title, padding=8)
            box.pack(side="left", fill="both", expand=True, padx=4)
            for b in books:
                avg, n = reviews.weighted_avg(self.store, b["book_id"])
                ttk.Label(box, text=f'{b["title"]} — {avg} ({n} reviews)').pack(anchor="w")
            if not books:
                ttk.Label(box, text="Nothing here yet.", style="Sub.TLabel").pack(anchor="w")


if __name__ == "__main__":
    App(Store(DATA_DIR)).mainloop()
