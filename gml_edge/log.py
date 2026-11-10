"""Journalisation embarquée : console + fichier, format court et lisible.

Chaque ligne commence par une étiquette entre crochets ([ALERT ZFE], [WARN]...)
pour être filtrable facilement (grep) et lisible pendant la démonstration.
"""
import os
import sys
from datetime import datetime

_LOG_FILE = None


def setup(log_path=None):
    """Active l'écriture dans un fichier de log (en plus de la console)."""
    global _LOG_FILE
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
            _LOG_FILE = open(log_path, "a", encoding="utf-8")
        except OSError as exc:  # le log fichier est un plus : jamais bloquant
            _LOG_FILE = None
            emit("WARN", f"Impossible d'ouvrir le fichier de log ({exc}) : console uniquement")


def emit(tag, message):
    """Écrit une ligne '[TAG] message' horodatée."""
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"{now} [{tag}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:  # console Windows sans UTF-8
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    if _LOG_FILE:
        try:
            _LOG_FILE.write(line + "\n")
            _LOG_FILE.flush()
        except OSError:
            pass


def close():
    global _LOG_FILE
    if _LOG_FILE:
        _LOG_FILE.close()
        _LOG_FILE = None


def use_utf8_console():
    """Évite les erreurs d'encodage sur les consoles Windows."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
