"""Avvio Waitress con una sola conferma di arresto da console."""

from __future__ import annotations

import os
import signal


def enable_console_ctrl_c() -> None:
    """Riabilita CTRL+C quando Python viene avviato con ``start /b``."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_handler = kernel32.SetConsoleCtrlHandler
    set_handler.argtypes = (ctypes.c_void_p, wintypes.BOOL)
    set_handler.restype = wintypes.BOOL
    if not set_handler(None, False):
        raise ctypes.WinError(ctypes.get_last_error())


def stop_confirmed(answer: str) -> bool:
    """Accetta le risposte italiane affermative alla sola domanda sul server."""
    return answer.strip().casefold() in {"s", "si", "sì"}


def run() -> int:
    from waitress import create_server

    from config.wsgi import application

    port = int(os.environ.get("SERVER_PORT", "8765"))
    server = create_server(application, host="0.0.0.0", port=port, threads=8)
    stop_requested = False

    def request_stop(_signal_number, _frame):
        nonlocal stop_requested
        if stop_requested:
            return
        try:
            answer = input("\nInterrompere il server? [s/N]: ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if not stop_confirmed(answer):
            print("Arresto annullato. Il server resta attivo.")
            return
        stop_requested = True
        print("Arresto di server e script in corso...")
        server.close()
        raise SystemExit(130)

    enable_console_ctrl_c()
    signal.signal(signal.SIGINT, request_stop)
    print(f"Server LAN attivo sulla porta {port}.")
    print("Premere CTRL+C per arrestare server e script.")
    try:
        server.run()
    finally:
        server.close()
    return 130 if stop_requested else 0


if __name__ == "__main__":
    raise SystemExit(run())
