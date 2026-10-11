"""tkinter GUI shell for psxhacks-updater.

A single main window with a swappable content frame, not a single
fixed-purpose dialog flow -- v1 has two pages: the status page (branch
dropdown, status/progress/log, Install/Update + Reinstall + History
buttons) and the history page (pick any commit on the selected branch and
switch to it). This shape means a later page (planned: a guided
master/slave sim setup wizard, an override-file wizard) is additive via
show_page() rather than a rewrite.

The actual sync/manifest/self-update work happens on a background thread
(it does blocking network/subprocess/hashing I/O); only this module's
methods are ever allowed to touch a Tk widget, and only from the Tk main
thread. The public methods below are the one safe bridge: they may be
called from either thread and take care of hopping onto the main thread
themselves when needed.
"""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class UpdaterWindow:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """The main window: status page, plus the commit-history page."""

    def __init__(self, title="psxhacks-updater"):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("620x440")
        self.root.minsize(460, 320)

        self._queue = queue.Queue()
        self._on_branch_changed = None
        self._on_update_clicked = None
        self._on_reinstall_clicked = None
        self._on_history_clicked = None
        self._on_history_switch_clicked = None
        self._on_history_back_clicked = None

        self.content_frame = ttk.Frame(self.root)
        self.content_frame.pack(fill="both", expand=True)

        self.branch_combo = None
        self.update_button = None
        self.reinstall_button = None
        self.history_button = None
        self.status_label = None
        self.progress = None
        self.log_text = None
        self.history_tree = None
        self.history_detail = None
        self.history_switch_button = None
        self._history_commits_by_sha = {}
        self.show_page(self._build_status_page)

        self.root.after(100, self._drain_queue)

    # -- status page --

    def _build_status_page(self, frame):
        top_row = ttk.Frame(frame)
        top_row.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(top_row, text="Branch:").pack(side="left")
        self.branch_combo = ttk.Combobox(top_row, state="readonly", width=20)
        self.branch_combo.pack(side="left", padx=(5, 10))
        self.branch_combo.bind("<<ComboboxSelected>>", self._handle_branch_changed)

        self.update_button = ttk.Button(
            top_row, text="Update", command=self._handle_update_clicked, state="disabled")
        self.update_button.pack(side="left", padx=(0, 5))

        self.reinstall_button = ttk.Button(
            top_row, text="Reinstall", command=self._handle_reinstall_clicked,
            state="disabled")
        self.reinstall_button.pack(side="left", padx=(0, 5))

        self.history_button = ttk.Button(
            top_row, text="History...", command=self._handle_history_clicked,
            state="disabled")
        self.history_button.pack(side="left")

        self.status_label = ttk.Label(frame, text="Starting...", anchor="w")
        self.status_label.pack(fill="x", padx=10, pady=(10, 0))

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(5, 5))

        self.log_text = tk.Text(frame, height=12, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # -- history page --

    def _build_history_page(self, frame):
        columns = ("short_sha", "author_date", "author_name", "summary")
        headings = {"short_sha": "Commit", "author_date": "Date",
                    "author_name": "Author", "summary": "Summary"}
        widths = {"short_sha": 80, "author_date": 150, "author_name": 140, "summary": 220}

        self.history_tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="browse", height=10)
        for col in columns:
            self.history_tree.heading(col, text=headings[col])
            self.history_tree.column(col, width=widths[col], stretch=col == "summary")
        self.history_tree.pack(fill="both", expand=True, padx=10, pady=(10, 5))
        self.history_tree.bind("<<TreeviewSelect>>", self._handle_history_row_selected)

        self.history_detail = tk.Text(frame, height=8, state="disabled", wrap="word")
        self.history_detail.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(
            button_row, text="Back", command=self._handle_history_back_clicked
        ).pack(side="left")
        self.history_switch_button = ttk.Button(
            button_row, text="Switch to this commit",
            command=self._handle_history_switch_clicked, state="disabled")
        self.history_switch_button.pack(side="left", padx=(5, 0))

    def show_history_page(self, commits):
        """Switch to the history page populated with commits (newest first).

        commits is the list pu_sync.list_commits() returns. Main-thread
        only (it's always reached via an on_done callback, never called
        directly from the worker thread).
        """
        self._history_commits_by_sha = {c["sha"]: c for c in commits}
        self.show_page(self._build_history_page)
        for commit in commits:
            self.history_tree.insert(
                "", "end", iid=commit["sha"],
                values=(commit["short_sha"], commit["author_date"],
                        commit["author_name"], commit["summary"]))

    def show_status_page(self):
        """Switch back to the status page. Main-thread only."""
        self.show_page(self._build_status_page)

    def show_page(self, builder):
        """Clear the content frame and repopulate it via builder(frame).

        Main-thread only.
        """
        for child in self.content_frame.winfo_children():
            child.destroy()
        builder(self.content_frame)

    # -- event wiring --

    def bind_branch_changed(self, callback):
        """callback(branch) runs on the main thread when the user picks a
        different branch from the dropdown."""
        self._on_branch_changed = callback

    def bind_update_clicked(self, callback):
        """callback(branch) runs on the main thread when the Install/Update
        button is clicked."""
        self._on_update_clicked = callback

    def bind_reinstall_clicked(self, callback):
        """callback(branch) runs on the main thread when the Reinstall
        button is clicked."""
        self._on_reinstall_clicked = callback

    def bind_history_clicked(self, callback):
        """callback(branch) runs on the main thread when the History...
        button is clicked."""
        self._on_history_clicked = callback

    def bind_history_switch_clicked(self, callback):
        """callback(commit_sha) runs on the main thread when "Switch to
        this commit" is clicked, for whichever row is currently
        selected."""
        self._on_history_switch_clicked = callback

    def bind_history_back_clicked(self, callback):
        """callback() runs on the main thread when the history page's Back
        button is clicked."""
        self._on_history_back_clicked = callback

    def _handle_branch_changed(self, _event):
        if self._on_branch_changed:
            self._on_branch_changed(self.branch_combo.get())

    def _handle_update_clicked(self):
        if self._on_update_clicked:
            self._on_update_clicked(self.branch_combo.get())

    def _handle_reinstall_clicked(self):
        if self._on_reinstall_clicked:
            self._on_reinstall_clicked(self.branch_combo.get())

    def _handle_history_clicked(self):
        if self._on_history_clicked:
            self._on_history_clicked(self.branch_combo.get())

    def _handle_history_row_selected(self, _event):
        selection = self.history_tree.selection()
        self.history_switch_button.configure(state="normal" if selection else "disabled")
        if not selection:
            return
        commit = self._history_commits_by_sha.get(selection[0])
        if commit is None:
            return
        detail = (
            f"commit {commit['sha']}\n"
            f"Author:    {commit['author_name']} <{commit['author_email']}>\n"
            f"Date:      {commit['author_date']}\n"
            f"Committer: {commit['committer_name']}\n"
            f"Committer date: {commit['committer_date']}\n\n"
            f"{commit['message']}\n")
        self.history_detail.config(state="normal")
        self.history_detail.delete("1.0", "end")
        self.history_detail.insert("1.0", detail)
        self.history_detail.config(state="disabled")

    def _handle_history_switch_clicked(self):
        selection = self.history_tree.selection()
        if selection and self._on_history_switch_clicked:
            self._on_history_switch_clicked(selection[0])

    def _handle_history_back_clicked(self):
        if self._on_history_back_clicked:
            self._on_history_back_clicked()

    # -- the main-thread <-> worker-thread bridge --

    def _drain_queue(self):
        try:
            while True:
                func = self._queue.get_nowait()
                func()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_queue)

    def _invoke(self, func):
        """Run func on the Tk main thread. Safe from any thread, fire-and-forget."""
        self._queue.put(func)

    def _invoke_and_wait(self, func):
        """Run func on the Tk main thread and block until it returns its result.

        Safe to call from either thread: if already on the main thread
        (e.g. from inside a button-click handler), runs func immediately
        rather than queuing it -- queuing and waiting on our own thread
        would deadlock, since draining the queue is itself a main-thread/
        mainloop activity.
        """
        if threading.current_thread() is threading.main_thread():
            return func()

        event = threading.Event()
        result = {}

        def wrapper():
            result["value"] = func()
            event.set()

        self._queue.put(wrapper)
        event.wait()
        return result["value"]

    # -- widget updates: fire-and-forget, safe from either thread --

    def set_branch_options(self, branches, selected):
        def apply():
            self.branch_combo.configure(values=branches)
            self.branch_combo.set(selected)
        self._invoke(apply)

    def set_branch_combo_enabled(self, enabled):
        self._invoke(lambda: self.branch_combo.configure(
            state="readonly" if enabled else "disabled"))

    def set_update_button(self, label=None, enabled=None):
        def apply():
            if label is not None:
                self.update_button.configure(text=label)
            if enabled is not None:
                self.update_button.configure(state="normal" if enabled else "disabled")
        self._invoke(apply)

    def set_reinstall_button(self, enabled=None):
        def apply():
            if enabled is not None:
                self.reinstall_button.configure(state="normal" if enabled else "disabled")
        self._invoke(apply)

    def set_history_button(self, enabled=None):
        def apply():
            if enabled is not None:
                self.history_button.configure(state="normal" if enabled else "disabled")
        self._invoke(apply)

    def set_status(self, text):
        self._invoke(lambda: self.status_label.config(text=text))

    def set_progress(self, fraction):
        value = max(0.0, min(1.0, fraction)) * 100
        self._invoke(lambda: self.progress.configure(value=value))

    def log(self, text):
        def append():
            self.log_text.config(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self._invoke(append)

    def clear_log(self):
        def clear():
            self.log_text.config(state="normal")
            self.log_text.delete("1.0", "end")
            self.log_text.config(state="disabled")
        self._invoke(clear)

    # -- dialogs: block until answered, safe from either thread --

    def ask_yes_no(self, title, message):
        return self._invoke_and_wait(
            lambda: messagebox.askyesno(title, message, parent=self.root))

    def show_error(self, title, message):
        self._invoke_and_wait(
            lambda: messagebox.showerror(title, message, parent=self.root))

    def show_warning(self, title, message):
        self._invoke_and_wait(
            lambda: messagebox.showwarning(title, message, parent=self.root))

    def show_info(self, title, message):
        self._invoke_and_wait(
            lambda: messagebox.showinfo(title, message, parent=self.root))

    # -- lifecycle --

    def run_in_background(self, func, *args, on_done=None, **kwargs):
        """Run func(*args, **kwargs) off the Tk main thread.

        func may freely call this window's set_status/set_progress/log/
        ask_yes_no/show_error/show_warning/show_info methods -- they're
        the one safe bridge back to the main thread. If on_done is given,
        it's scheduled on the main thread afterward as on_done(result,
        error) (error is None on success, the raised exception otherwise).
        """
        def worker():
            try:
                result = func(*args, **kwargs)
                error = None
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result = None
                error = exc
            if on_done is not None:
                self._invoke(lambda: on_done(result, error))

        threading.Thread(target=worker, daemon=True).start()

    def close(self):
        self.root.quit()
        self.root.destroy()

    def mainloop(self):
        self.root.mainloop()
