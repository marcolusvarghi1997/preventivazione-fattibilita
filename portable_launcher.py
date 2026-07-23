"""Launcher grafico predisposto per la compilazione Windows con Nuitka.

Nell'eseguibile distribuito l'utente non usa PowerShell né script: apre il file
.exe, poi gestisce utenti, branding e accesso LAN dal superadmin.
"""

# nuitka-project: --mode=onefile
# nuitka-project: --windows-console-mode=disable
# nuitka-project: --enable-plugin=tk-inter
# nuitka-project: --include-data-dir=templates=templates
# nuitka-project: --include-data-dir=static=static
# nuitka-project: --include-data-dir=staticfiles=staticfiles
# nuitka-project: --include-package=apps
# nuitka-project: --include-package=config
# nuitka-project: --include-package-data=django
# nuitka-project: --include-package-data=jazzmin

from __future__ import annotations

import os
import queue
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import BOTH, DISABLED, END, LEFT, NORMAL, Button, Frame, Label, StringVar, Text, Tk


def application_directory() -> Path:
    if "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = application_directory()
DATA_DIR = APP_DIR / "dati"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def persistent_secret_key() -> str:
    path = DATA_DIR / ".chiave_app"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(64)
    path.write_text(value, encoding="utf-8")
    return value


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "*")
os.environ.setdefault("DJANGO_SECRET_KEY", persistent_secret_key())
os.environ.setdefault("SQLITE_DB_PATH", str(DATA_DIR / "preventivi.sqlite3"))
os.environ.setdefault("MEDIA_ROOT", str(DATA_DIR / "media"))
os.environ.setdefault("STATIC_ROOT", str(DATA_DIR / "staticfiles"))


def first_free_port() -> int:
    requested = os.getenv("SERVER_PORT")
    candidates = [int(requested)] if requested else [8765, 8000, 9000]
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                continue
        return port
    raise RuntimeError("Nessuna porta disponibile tra 8765, 8000 e 9000.")


class PortableApplication:
    def __init__(self):
        self.root = Tk()
        self.root.title("Preventivazione e fattibilità")
        self.root.geometry("680x430")
        self.root.minsize(580, 360)
        self.status = StringVar(value="Preparazione dell'applicazione…")
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.server = None
        self.port = first_free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._build_window()
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

    def _build_window(self):
        Label(self.root, text="Preventivazione e fattibilità", font=("Segoe UI", 20, "bold")).pack(pady=(24, 4))
        Label(self.root, textvariable=self.status, font=("Segoe UI", 11)).pack(pady=(0, 18))
        actions = Frame(self.root)
        actions.pack(pady=4)
        self.open_button = Button(actions, text="Apri applicazione", command=lambda: webbrowser.open(self.url), state=DISABLED, width=20)
        self.open_button.pack(side=LEFT, padx=6)
        self.admin_button = Button(actions, text="Apri superadmin", command=lambda: webbrowser.open(f"{self.url}/admin/"), state=DISABLED, width=20)
        self.admin_button.pack(side=LEFT, padx=6)
        Button(actions, text="Arresta", command=self.stop, width=12).pack(side=LEFT, padx=6)
        Label(
            self.root,
            text="L'accesso dalla rete aziendale si attiva o disattiva in Superadmin → Configurazione azienda e rete.",
            wraplength=610,
            justify="center",
            fg="#4c5568",
        ).pack(pady=(18, 8))
        self.log = Text(self.root, height=10, state=DISABLED, font=("Consolas", 9), wrap="word")
        self.log.pack(fill=BOTH, expand=True, padx=20, pady=(0, 20))

    def write(self, message: str):
        self.log.configure(state=NORMAL)
        self.log.insert(END, message + "\n")
        self.log.see(END)
        self.log.configure(state=DISABLED)

    def start(self):
        threading.Thread(target=self._run_server, daemon=True).start()
        self.root.after(100, self._poll_messages)
        self.root.mainloop()

    def _run_server(self):
        try:
            import django

            django.setup()
            from django.core.management import call_command
            from waitress import create_server
            from config.wsgi import application

            self.messages.put(("log", "Aggiornamento del database…"))
            call_command("migrate", interactive=False, verbosity=0)
            call_command("seed_initial_data", verbosity=0)
            call_command("collectstatic", interactive=False, verbosity=0)
            self.server = create_server(application, host="0.0.0.0", port=self.port, threads=8)
            self.messages.put(("ready", f"Applicazione pronta: {self.url}"))
            self.server.run()
        except Exception as exc:  # pragma: no cover - dipende dall'ambiente Windows
            self.messages.put(("error", f"Avvio non riuscito: {exc}"))

    def _poll_messages(self):
        try:
            while True:
                kind, message = self.messages.get_nowait()
                self.write(message)
                if kind == "ready":
                    self.status.set("Applicazione avviata")
                    self.open_button.configure(state=NORMAL)
                    self.admin_button.configure(state=NORMAL)
                    webbrowser.open(self.url)
                elif kind == "error":
                    self.status.set("Errore di avvio")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_messages)

    def stop(self):
        if self.server is not None:
            self.server.close()
        self.root.destroy()


if __name__ == "__main__":
    PortableApplication().start()
