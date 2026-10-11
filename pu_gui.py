"""tkinter GUI shell for psxhacks-updater.

A single main window with a swappable content frame, not a single
fixed-purpose dialog flow -- v1 only ever shows one page (branch dropdown,
status/progress/log, and an Install/Update button), but this shape means
a later page (planned: a guided master/slave sim setup wizard, an
override-file wizard) is additive via show_page() rather than a rewrite.

The actual sync/manifest/self-update/venv-check work happens on a
background thread (it does blocking network/subprocess/hashing I/O); only
this module's methods are ever allowed to touch a Tk widget, and only from
the Tk main thread. The public methods below are the one safe bridge: they
may be called from either thread and take care of hopping onto the main
thread themselves when needed.
"""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class UpdaterWindow:  # pylint: disable=too-many-instance-attributes
    """The main window: branch picker, status/progress/log, Update button."""

    def __init__(self, title="psxhacks-updater"):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("560x400")
        self.root.minsize(420, 300)

        self._queue = queue.Queue()
        self._on_branch_changed = None
        self._on_update_clicked = None

        self.content_frame = ttk.Frame(self.root)
        self.content_frame.pack(fill="both", expand=True)

        self.branch_combo = None
        self.update_button = None
        self.status_label = None
        self.progress = None
        self.log_text = None
        self.show_page(self._build_status_page)

        self.root.after(100, self._drain_queue)

    # -- page content --

    def _build_status_page(self, frame):
        """The only page v1 needs. A future page gets its own _build_*_page
        method and is swapped in via show_page()."""
        top_row = ttk.Frame(frame)
        top_row.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(top_row, text="Branch:").pack(side="left")
        self.branch_combo = ttk.Combobox(top_row, state="readonly", width=20)
        self.branch_combo.pack(side="left", padx=(5, 10))
        self.branch_combo.bind("<<ComboboxSelected>>", self._handle_branch_changed)

        self.update_button = ttk.Button(
            top_row, text="Update", command=self._handle_update_clicked, state="disabled")
        self.update_button.pack(side="left")

        self.status_label = ttk.Label(frame, text="Starting...", anchor="w")
        self.status_label.pack(fill="x", padx=10, pady=(10, 0))

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=10, pady=(5, 5))

        self.log_text = tk.Text(frame, height=12, state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def show_page(self, builder):
        """Clear the content frame and repopulate it via builder(frame).

        Not exercised by v1 (which only ever shows the status page), but
        this is the hook a future page would use. Main-thread only.
        """
        for child in self.content_frame.winfo_children():
            child.destroy()
        builder(self.content_frame)

    # -- branch combo / update button event wiring --

    def bind_branch_changed(self, callback):
        """callback(branch_label) runs on the main thread when the user
        picks a different branch from the dropdown."""
        self._on_branch_changed = callback

    def bind_update_clicked(self, callback):
        """callback(branch_label) runs on the main thread when the
        Install/Update button is clicked."""
        self._on_update_clicked = callback

    def _handle_branch_changed(self, _event):
        if self._on_branch_changed:
            self._on_branch_changed(self.branch_combo.get())

    def _handle_update_clicked(self):
        if self._on_update_clicked:
            self._on_update_clicked(self.branch_combo.get())

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

    def set_branch_options(self, labels, selected):
        def apply():
            self.branch_combo.configure(values=labels)
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

    def show_info(self, title, message):
        self._invoke_and_wait(
            lambda: messagebox.showinfo(title, message, parent=self.root))

    # -- lifecycle --

    def run_in_background(self, func, *args, on_done=None, **kwargs):
        """Run func(*args, **kwargs) off the Tk main thread.

        func may freely call this window's set_status/set_progress/log/
        ask_yes_no/show_error/show_info methods -- they're the one safe
        bridge back to the main thread. If on_done is given, it's
        scheduled on the main thread afterward as on_done(result, error)
        (error is None on success, the raised exception otherwise).
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
