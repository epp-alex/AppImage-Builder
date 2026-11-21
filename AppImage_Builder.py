#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AppImage Builder – Oberfläche für build_appimage_v2.sh (Python)
                   und build_appimage_rust.sh (Rust)

1. Python-Datei ODER Cargo.toml auswählen
   -> Ordner, Programmname und Symbol werden übernommen
2. Python: Importe werden ausgewertet -> PACKAGES wird automatisch gesetzt
   Rust:   Name, Version, APP_ID und Beschreibung aus Cargo.toml / Quelltext
3. Optionen mit Haken ein-/ausschalten
4. "AppImage bauen" -> Ausgabe erscheint live im Fenster

Sprachen: Deutsch und Englisch sind eingebaut. Weitere Sprachen als JSON-Datei
in einen Ordner "lang" legen (neben diesem Programm oder in
~/.config/AppImageBuilder/lang/). Vorlage erzeugen:
    python3 AppImage_Builder.py --export-lang en > lang/es.json

Beide Build-Skripte sollten im selben Ordner liegen wie dieses Programm
(oder unter "Erweitert" bzw. "Rust" ausgewählt werden).
"""

import ast
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP_TITLE = "AppImage Builder"
# Ordner mit den Build-Skripten: neben diesem Programm, oder – wenn es als
# AppImage/PyInstaller-Programm läuft – im eingepackten Ordner.
HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SCRIPT = os.path.join(HERE, "build_appimage_v2.sh")
DEFAULT_RUST_SCRIPT = os.path.join(HERE, "build_appimage_rust.sh")
GLIBC_CHOICES = ["2.17", "2.28", "2.31", "2.35"]

CFG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                      os.path.join(os.path.expanduser("~"), ".config")),
                       "AppImageBuilder")
CFG_FILE = os.path.join(CFG_DIR, "einstellungen.json")

CATEGORIES = ["Utility;", "Education;", "Game;", "Office;", "AudioVideo;",
              "Graphics;", "Development;", "Network;", "Science;", "System;"]


# ======================================================================
#  SPRACHEN
#  Neue Sprache: entweder hier einen Block ergänzen, oder (ohne Code-
#  Änderung) eine Datei lang/<code>.json anlegen – siehe --export-lang.
#  "_name" ist der Name der Sprache in der Sprache selbst.
#  Fehlt ein Text, wird Englisch genommen, danach Deutsch.
# ======================================================================
TRANSLATIONS = {
    "de": {
        "_name": "Deutsch",
        "language": "Sprache:",
        # Programm
        "frm_program": "Programm",
        "lbl_project": "Projektdatei:",
        "btn_choose": "Auswählen ...",
        "lbl_folder": "Ordner:",
        "lbl_name": "Programmname:",
        "lbl_icon": "Symbol (PNG):",
        "lbl_category": "Kategorie:",
        # Pakete
        "frm_packages": "Pakete (aus den Importen erkannt, änderbar)",
        "btn_redetect": "Neu erkennen",
        "no_file": "Noch keine Datei ausgewählt.",
        # Optionen
        "frm_options": "Optionen",
        "opt_clean": "Komplett neu bauen (Python-Umgebung frisch anlegen)",
        "opt_strip": "System-Bibliotheken nicht einpacken (läuft auch auf älteren Linux)",
        "opt_target": "Pakete in der Ausgabe für ältere Systeme wählen (empfohlen)",
        "opt_integrate": "Beim ersten Start mit Symbol ins Startmenü eintragen",
        "opt_glibc": "glibc-Prüfung: Build abbrechen, wenn mehr nötig als",
        "opt_glibc_hint": "(2.17 = fast jedes Linux; PySide6 hebt auf 2.34 an)",
        # Erweitert
        "frm_advanced": "Erweitert",
        "lbl_pyver": "Python-Version:",
        "lbl_pysrc": "Python-Quelle:",
        "lbl_data": "Datendateien:",
        "lbl_collect": "Komplett einpacken:",
        "lbl_script": "Build-Skript:",
        # Rust
        "frm_rust": "Rust-Programm",
        "lbl_appid": "Kennung (APP_ID):",
        "lbl_comment": "Beschreibung:",
        "lbl_rglibc": "Älteste glibc:",
        "rglibc_hint": "(2.17 = fast jedes Linux, 2.28 = ab Mint 20 / Ubuntu 20.04 / Debian 10)",
        "lbl_rscript": "Rust-Build-Skript:",
        # Knöpfe / Status
        "btn_build": "AppImage bauen",
        "btn_cancel": "Abbrechen",
        "btn_dist": "dist-Ordner öffnen",
        "st_ready": "Bereit",
        "st_building": "Baue ...",
        "st_done": "Fertig",
        "st_cancelled": "Abgebrochen",
        "st_error": "Fehler (Code {code})",
        # Dateidialoge
        "dlg_main": "Python-Hauptdatei oder Cargo.toml wählen",
        "dlg_icon": "Symbol wählen",
        "dlg_script": "build_appimage_v2.sh wählen",
        "dlg_rscript": "build_appimage_rust.sh wählen",
        "ft_py_or_rust": "Python oder Rust",
        "ft_python": "Python",
        "ft_rust": "Rust (Cargo.toml)",
        "ft_png": "PNG-Bild",
        "ft_shell": "Shell-Skript",
        "ft_all": "Alle Dateien",
        # Analyse Python
        "an_gui": "Oberfläche: {names}",
        "an_tk": "Oberfläche: Tkinter (schon in Python enthalten, kein Paket nötig)",
        "an_no_gui": "Keine Oberflächen-Bibliothek gefunden.",
        "an_packages": "Erkannte Pakete: {names}",
        "an_none": "keine",
        "an_local": "Eigene Module (werden mit eingepackt): {names}",
        "an_requirements": "requirements.txt gefunden – wird zusätzlich installiert.",
        "an_hint": "Hinweis: {text}",
        "an_read_error": "Fehler beim Lesen: {text}",
        "note_windows": "{name}: nur unter Windows – wird unter Linux nicht gebraucht/geht nicht",
        "note_gi": "{name}: PyGObject (GTK) – über pip schwierig, besser vermeiden",
        "note_dbus": "{name}: dbus-python – braucht System-Bibliotheken",
        "note_multi_gui": "Mehrere Oberflächen-Bibliotheken gefunden: {names} – meist braucht man nur eine.",
        "note_qt6": "PyQt6/PySide2 sind im Build-Skript nicht besonders berücksichtigt.",
        # Analyse Rust
        "ru_bin": "Programmdatei: {bin}    Version: {version}",
        "ru_appid_found": "APP_ID im Quelltext gefunden ({file}): {appid}",
        "ru_appid_missing": "Keine APP_ID im Quelltext gefunden – Kennung bitte prüfen "
                            "(sie muss zur Fenster-Kennung im Programm passen).",
        "ru_no_icon": "Kein PNG-Symbol gefunden – bitte oben auswählen.",
        "ru_no_cargo": "WARNUNG: cargo nicht gefunden – Rust ist auf diesem Rechner nicht installiert.",
        "ru_no_zig": "WARNUNG: cargo-zigbuild fehlt – die glibc-Einstellung wirkt dann nicht. "
                     "Installieren: cargo install cargo-zigbuild && pip install ziglang",
        "ru_zig_ok": "cargo-zigbuild vorhanden – baut für die gewählte glibc.",
        "ru_result": "Ergebnis: dist/{file}",
        # Meldungen
        "log_loaded": "Gespeicherte Einstellungen für {name} geladen.",
        "log_building": "Baue {name} aus {path}",
        "log_done": "Fertig: {path}",
        "log_cancelled": "Abgebrochen.",
        "log_failed": "Build fehlgeschlagen (Code {code}). Siehe Ausgabe oben.",
        "log_note_lang": "Hinweis: Die Ausgabe der Build-Skripte ist auf Deutsch.",
        "msg_created": "AppImage erstellt:\n{path}",
        "msg_failed": "Build fehlgeschlagen. Details stehen in der Ausgabe.",
        "err_script": "Build-Skript nicht gefunden:\n{path}\n\nUnter 'Erweitert' auswählen.",
        "err_rscript": "Rust-Build-Skript nicht gefunden:\n{path}\n\nIm Bereich 'Rust-Programm' auswählen.",
        "err_no_cargo": "cargo wurde nicht gefunden. Ist Rust installiert?",
        "err_name": "Bitte einen Programmnamen eingeben.",
        "err_name_appid": "Bitte Programmname und Kennung (APP_ID) eingeben.",
        "err_icon": "Bitte ein Symbol (PNG-Datei) auswählen.",
        "err_glibc": "glibc-Grenze bitte als Zahl wie 2.17 eingeben.",
        "err_start": "Konnte das Build-Skript nicht starten:\n{error}",
        "err_open": "Ordner konnte nicht geöffnet werden:\n{error}",
        "ask_quit": "Es läuft noch ein Build. Abbrechen und beenden?",
        # Werkzeuge
        "tool_no_uv": "WARNUNG: uv nicht gefunden – wird zum Bauen gebraucht. "
                      "Installieren: curl -LsSf https://astral.sh/uv/install.sh | sh",
        "tool_no_curl": "WARNUNG: curl nicht gefunden – wird zum Herunterladen gebraucht. "
                        "Installieren: sudo apt install curl",
        "err_no_uv": "uv ist nicht installiert, wird aber zum Bauen von Python-Programmen gebraucht.\n\n"
                     "Im Terminal installieren:\n"
                     "curl -LsSf https://astral.sh/uv/install.sh | sh\n\n"
                     "Danach einfach noch einmal auf „AppImage bauen“ klicken.",
        "err_no_curl": "curl ist nicht installiert, wird aber zum Herunterladen gebraucht.\n\n"
                       "Im Terminal installieren:\nsudo apt install curl",
    },

    "en": {
        "_name": "English",
        "language": "Language:",
        "frm_program": "Program",
        "lbl_project": "Project file:",
        "btn_choose": "Choose ...",
        "lbl_folder": "Folder:",
        "lbl_name": "Program name:",
        "lbl_icon": "Icon (PNG):",
        "lbl_category": "Category:",
        "frm_packages": "Packages (detected from imports, editable)",
        "btn_redetect": "Detect again",
        "no_file": "No file selected yet.",
        "frm_options": "Options",
        "opt_clean": "Clean build (create a fresh Python environment)",
        "opt_strip": "Do not bundle system libraries (also runs on older Linux)",
        "opt_target": "Install packages built for older systems (recommended)",
        "opt_integrate": "Add to the application menu with icon on first start",
        "opt_glibc": "glibc check: stop the build if it needs more than",
        "opt_glibc_hint": "(2.17 = almost any Linux; PySide6 raises it to 2.34)",
        "frm_advanced": "Advanced",
        "lbl_pyver": "Python version:",
        "lbl_pysrc": "Python source:",
        "lbl_data": "Data files:",
        "lbl_collect": "Collect completely:",
        "lbl_script": "Build script:",
        "frm_rust": "Rust program",
        "lbl_appid": "Identifier (APP_ID):",
        "lbl_comment": "Description:",
        "lbl_rglibc": "Oldest glibc:",
        "rglibc_hint": "(2.17 = almost any Linux, 2.28 = Mint 20 / Ubuntu 20.04 / Debian 10 and newer)",
        "lbl_rscript": "Rust build script:",
        "btn_build": "Build AppImage",
        "btn_cancel": "Cancel",
        "btn_dist": "Open dist folder",
        "st_ready": "Ready",
        "st_building": "Building ...",
        "st_done": "Done",
        "st_cancelled": "Cancelled",
        "st_error": "Error (code {code})",
        "dlg_main": "Choose Python main file or Cargo.toml",
        "dlg_icon": "Choose icon",
        "dlg_script": "Choose build_appimage_v2.sh",
        "dlg_rscript": "Choose build_appimage_rust.sh",
        "ft_py_or_rust": "Python or Rust",
        "ft_python": "Python",
        "ft_rust": "Rust (Cargo.toml)",
        "ft_png": "PNG image",
        "ft_shell": "Shell script",
        "ft_all": "All files",
        "an_gui": "GUI toolkit: {names}",
        "an_tk": "GUI toolkit: Tkinter (included in Python, no package needed)",
        "an_no_gui": "No GUI library found.",
        "an_packages": "Detected packages: {names}",
        "an_none": "none",
        "an_local": "Own modules (bundled automatically): {names}",
        "an_requirements": "requirements.txt found – will be installed as well.",
        "an_hint": "Note: {text}",
        "an_read_error": "Could not read: {text}",
        "note_windows": "{name}: Windows only – not needed / not available on Linux",
        "note_gi": "{name}: PyGObject (GTK) – hard to install via pip, better avoid",
        "note_dbus": "{name}: dbus-python – needs system libraries",
        "note_multi_gui": "Several GUI libraries found: {names} – usually only one is needed.",
        "note_qt6": "PyQt6/PySide2 are not specially handled by the build script.",
        "ru_bin": "Binary: {bin}    Version: {version}",
        "ru_appid_found": "APP_ID found in source ({file}): {appid}",
        "ru_appid_missing": "No APP_ID found in the source – please check the identifier "
                            "(it must match the window id set by the program).",
        "ru_no_icon": "No PNG icon found – please choose one above.",
        "ru_no_cargo": "WARNING: cargo not found – Rust is not installed on this computer.",
        "ru_no_zig": "WARNING: cargo-zigbuild is missing – the glibc setting will have no effect. "
                     "Install: cargo install cargo-zigbuild && pip install ziglang",
        "ru_zig_ok": "cargo-zigbuild found – builds for the selected glibc.",
        "ru_result": "Result: dist/{file}",
        "log_loaded": "Loaded saved settings for {name}.",
        "log_building": "Building {name} from {path}",
        "log_done": "Done: {path}",
        "log_cancelled": "Cancelled.",
        "log_failed": "Build failed (code {code}). See output above.",
        "log_note_lang": "Note: the build scripts print their output in German.",
        "msg_created": "AppImage created:\n{path}",
        "msg_failed": "Build failed. See the output for details.",
        "err_script": "Build script not found:\n{path}\n\nChoose it under 'Advanced'.",
        "err_rscript": "Rust build script not found:\n{path}\n\nChoose it in the 'Rust program' section.",
        "err_no_cargo": "cargo was not found. Is Rust installed?",
        "err_name": "Please enter a program name.",
        "err_name_appid": "Please enter a program name and an identifier (APP_ID).",
        "err_icon": "Please choose an icon (PNG file).",
        "err_glibc": "Please enter the glibc limit as a number like 2.17.",
        "err_start": "Could not start the build script:\n{error}",
        "err_open": "Could not open the folder:\n{error}",
        "ask_quit": "A build is still running. Cancel it and quit?",
        "tool_no_uv": "WARNING: uv not found – it is needed for building. "
                      "Install: curl -LsSf https://astral.sh/uv/install.sh | sh",
        "tool_no_curl": "WARNING: curl not found – it is needed for downloads. "
                        "Install: sudo apt install curl",
        "err_no_uv": "uv is not installed, but it is needed to build Python programs.\n\n"
                     "Install it in a terminal:\n"
                     "curl -LsSf https://astral.sh/uv/install.sh | sh\n\n"
                     "Then simply click “Build AppImage” again.",
        "err_no_curl": "curl is not installed, but it is needed for downloads.\n\n"
                       "Install it in a terminal:\nsudo apt install curl",
    },
}

LANG = "de"


def _load_extra_languages():
    """Zusätzliche Sprachen aus lang/*.json laden (neben dem Programm, im
    eingepackten Ordner und in ~/.config/AppImageBuilder/lang/)."""
    folders = [os.path.join(HERE, "lang"), os.path.join(CFG_DIR, "lang")]
    if not getattr(sys, "frozen", False):
        folders.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang"))
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            code = fn[:-5].lower()
            try:
                with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"[lang] {fn}: {e}", file=sys.stderr)
                continue
            if isinstance(data, dict):
                TRANSLATIONS.setdefault(code, {}).update(
                    {k: v for k, v in data.items() if isinstance(v, str)})
                TRANSLATIONS[code].setdefault("_name", code)


def detect_language(saved=""):
    """Gespeicherte Sprache, sonst Systemsprache, sonst Englisch."""
    if saved in TRANSLATIONS:
        return saved
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        for part in val.split(":"):
            code = part.split("_")[0].split(".")[0].lower()
            if code in TRANSLATIONS:
                return code
    return "en"


def tr(key, **kw):
    """Text in der aktuellen Sprache (Rückfall: Englisch, dann Deutsch)."""
    for code in (LANG, "en", "de"):
        text = TRANSLATIONS.get(code, {}).get(key)
        if text is not None:
            break
    else:
        text = key
    try:
        return text.format(**kw) if kw else text
    except (KeyError, IndexError, ValueError):
        return text


# ----------------------------------------------------------------------
#  Import-Name  ->  Paketname bei PyPI (nur wo die Namen verschieden sind)
# ----------------------------------------------------------------------
PYPI_NAMES = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "serial": "pyserial",
    "usb": "pyusb",
    "Xlib": "python-xlib",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "OpenGL": "PyOpenGL",
    "fitz": "PyMuPDF",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "jwt": "PyJWT",
    "magic": "python-magic",
    "vlc": "python-vlc",
    "attr": "attrs",
    "telegram": "python-telegram-bot",
    "odf": "odfpy",
    "mido": "mido",
    "rtmidi": "python-rtmidi",
    "sounddevice": "sounddevice",
    "simpleaudio": "simpleaudio",
    "playsound": "playsound",
    "fpdf": "fpdf2",
    "reportlab": "reportlab",
    "qrcode": "qrcode",
    "barcode": "python-barcode",
    "ttkbootstrap": "ttkbootstrap",
    "customtkinter": "customtkinter",
}

# Module, die zu einem anderen Paket gehören (kein eigenes PACKAGES nötig)
BELONGS_TO = {
    "shiboken6": "PySide6",
    "sip": "PyQt5",
    "PyQt5_sip": "PyQt5",
}

# Nur unter Windows vorhanden -> nicht installierbar, Hinweis anzeigen
WINDOWS_ONLY = {"win32api", "win32con", "win32gui", "win32com", "pywintypes",
                "winreg", "winsound", "msvcrt", "_winapi", "wmi", "pythoncom"}

# Unter Linux problematisch: braucht System-Bibliotheken, nicht über pip
SYSTEM_ONLY = {"gi": "note_gi", "dbus": "note_dbus"}

GUI_TOOLKITS = ("PySide6", "PyQt5", "PyQt6", "PySide2")

try:
    STDLIB = set(sys.stdlib_module_names)          # ab Python 3.10
except AttributeError:                             # Notlösung für ältere Pythons
    STDLIB = {"os", "sys", "re", "json", "math", "time", "datetime", "random",
              "tkinter", "threading", "subprocess", "shutil", "pathlib", "glob",
              "collections", "itertools", "functools", "typing", "logging",
              "unicodedata", "locale", "hashlib", "traceback", "ctypes", "io",
              "string", "struct", "copy", "csv", "sqlite3", "zipfile", "tempfile",
              "urllib", "http", "socket", "queue", "signal", "platform", "uuid",
              "base64", "configparser", "argparse", "textwrap", "enum", "abc",
              "dataclasses", "decimal", "fractions", "statistics", "wave",
              "webbrowser", "xml", "html", "email", "gettext", "calendar"}


def clean_env():
    """Umgebung für externe Programme (Build-Skript, Dateimanager) ohne die
    Variablen, die AppImage/PyInstaller setzen. Sonst würden uv, cargo oder
    appimagetool die eingepackten Bibliotheken dieses Programms laden."""
    env = dict(os.environ)
    meipass = getattr(sys, "_MEIPASS", "")
    appdir = env.get("APPDIR", "")

    def inside(x):
        return bool((meipass and x.startswith(meipass)) or (appdir and x.startswith(appdir)))

    for var in ("LD_LIBRARY_PATH", "LD_PRELOAD", "TCL_LIBRARY", "TK_LIBRARY", "PYTHONPATH",
                "PYTHONHOME", "SSL_CERT_FILE", "GDK_PIXBUF_MODULE_FILE", "GIO_MODULE_DIR",
                "GTK_PATH", "QT_PLUGIN_PATH", "PATH", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS"):
        orig = env.pop(var + "_ORIG", None)       # PyInstaller merkt sich die Originale
        if orig is not None:
            env[var] = orig
        if var in env:
            parts = [x for x in env[var].split(os.pathsep) if x and not inside(x)]
            if parts:
                env[var] = os.pathsep.join(parts)
            elif var != "PATH":
                env.pop(var)
    for var in ("APPDIR", "APPIMAGE", "ARGV0", "OWD"):
        env.pop(var, None)
    return env


# Ordner, in die sich uv und Rust installieren. Beim Start aus dem Startmenü
# oder als AppImage stehen sie oft NICHT im Suchpfad (PATH) - deshalb dort
# zusätzlich suchen und den Build-Skripten mitgeben.
EXTRA_TOOL_DIRS = [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin")]


def find_tool(name):
    """Pfad zu einem Programm (uv, curl, cargo …) oder "" wenn nicht vorhanden."""
    import shutil
    path = clean_env().get("PATH", os.defpath)
    found = shutil.which(name, path=path)
    if found:
        return found
    for d in EXTRA_TOOL_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return ""


def add_tool_dirs(env):
    """Die Zusatz-Ordner an PATH anhängen, damit die Build-Skripte uv/cargo finden."""
    parts = env.get("PATH", os.defpath).split(os.pathsep)
    for d in EXTRA_TOOL_DIRS:
        if os.path.isdir(d) and d not in parts:
            parts.append(d)
    env["PATH"] = os.pathsep.join(p for p in parts if p)
    return env


def _existing_script(saved, default):
    """Gespeicherten Skript-Pfad nehmen, wenn es ihn noch gibt (und er nicht
    im Temp-Ordner eines früheren AppImage-Starts liegt), sonst den eingebauten."""
    if saved and os.path.isfile(saved) and "/.mount_" not in saved and "/_MEI" not in saved:
        return saved
    return default


# ----------------------------------------------------------------------
#  Import-Analyse
# ----------------------------------------------------------------------
def _imports_of(path):
    """Alle Top-Level-Modulnamen, die eine Datei importiert."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=path)
    except (SyntaxError, OSError) as e:
        return set(), str(e)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:          # keine relativen Importe
                names.add(node.module.split(".")[0])
    return names, None


def analyze(main_path):
    """Wertet die Importe des Hauptprogramms und aller eigenen Module aus,
    die es (auch über Umwege) importiert. Andere .py-Dateien im Ordner,
    die nicht dazugehören, werden NICHT mitgezählt.
    Hinweise kommen als (Text-Schlüssel, Werte) zurück, damit sie in jeder
    Sprache angezeigt werden können."""
    folder = os.path.dirname(main_path)
    local_files = {}
    for entry in os.listdir(folder):
        p = os.path.join(folder, entry)
        if entry.endswith(".py") and os.path.isfile(p):
            local_files[entry[:-3]] = [p]
        elif os.path.isdir(p) and os.path.isfile(os.path.join(p, "__init__.py")):
            files = []
            for root, dirs, fs in os.walk(p):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                files += [os.path.join(root, x) for x in fs if x.endswith(".py")]
            local_files[entry] = files

    seen_files, todo = set(), [main_path]
    third_party, errors = set(), []
    uses_tk, local_used = False, set()
    while todo:
        f = todo.pop()
        if f in seen_files:
            continue
        seen_files.add(f)
        names, err = _imports_of(f)
        if err:
            errors.append(f"{os.path.basename(f)}: {err}")
        for n in names:
            if n == "tkinter":
                uses_tk = True
            if n in local_files:
                local_used.add(n)
                todo.extend(local_files[n])
            elif n in STDLIB or n == "__future__":
                continue
            else:
                third_party.add(n)

    packages, notes = [], []
    for n in sorted(third_party, key=str.lower):
        if n in WINDOWS_ONLY:
            notes.append(("note_windows", {"name": n}))
            continue
        if n in SYSTEM_ONLY:
            notes.append((SYSTEM_ONLY[n], {"name": n}))
            continue
        pkg = BELONGS_TO.get(n) or PYPI_NAMES.get(n, n)
        if pkg not in packages:
            packages.append(pkg)

    toolkits = [p for p in packages if p in GUI_TOOLKITS]
    if len(toolkits) > 1:
        notes.append(("note_multi_gui", {"names": ", ".join(toolkits)}))
    if "PyQt6" in packages or "PySide2" in packages:
        notes.append(("note_qt6", {}))

    # GUI-Bibliothek zuerst, Rest alphabetisch
    packages.sort(key=lambda p: (p not in GUI_TOOLKITS, p.lower()))
    return {
        "packages": packages,
        "uses_tk": uses_tk,
        "local": sorted(local_used),
        "notes": notes,
        "errors": errors,
        "has_requirements": os.path.isfile(os.path.join(folder, "requirements.txt")),
    }


def find_icon(folder, name):
    """Passendes Symbol im Ordner suchen."""
    candidates = [f"{name}.png", "icon.png", "Icon.png", "logo.png"]
    for c in candidates:
        p = os.path.join(folder, c)
        if os.path.isfile(p):
            return p
    pngs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
    return os.path.join(folder, pngs[0]) if pngs else ""


# ----------------------------------------------------------------------
#  Rust: Werte aus Cargo.toml und dem Quelltext lesen
# ----------------------------------------------------------------------
def _toml_sections(path):
    """Sehr einfacher TOML-Leser für die Werte, die wir brauchen.
    Ergebnis: {"package": {...}, "bin": [{...}, ...]}"""
    try:
        import tomllib                                   # ab Python 3.11
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return {"package": data.get("package", {}) or {}, "bin": data.get("bin", []) or []}
    except Exception:
        pass
    import re
    result, cur = {"package": {}, "bin": []}, None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            if line == "[package]":
                cur = result["package"]
            elif line == "[[bin]]":
                cur = {}
                result["bin"].append(cur)
            elif line.startswith("["):
                cur = None
            elif cur is not None:
                m = re.match(r'([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"', line)
                if m:
                    cur[m.group(1)] = m.group(2)
    return result


def analyze_rust(cargo_path):
    import re
    folder = os.path.dirname(cargo_path)
    t = _toml_sections(cargo_path)
    pkg = t["package"]
    bins = t["bin"]
    first_bin = bins[0] if bins else {}
    bin_name = first_bin.get("name") or pkg.get("name") or os.path.basename(folder)
    bin_path = first_bin.get("path") or "src/main.rs"
    version = str(pkg.get("version") or "1.0.0")
    description = str(pkg.get("description") or "")

    # APP_ID aus dem Quelltext suchen (muss zum Fenster passen)
    app_id, app_id_file = "", ""
    patterns = [r'const\s+APP_ID\s*:\s*&(?:\'static\s+)?str\s*=\s*"([^"]+)"',
                r'with_app_id\(\s*"([^"]+)"', r'app_id\s*:\s*Some\(\s*"([^"]+)"',
                r'with_class\(\s*"([^"]+)"']
    src_dir = os.path.join(folder, "src")
    for root, dirs, files in os.walk(src_dir if os.path.isdir(src_dir) else folder):
        dirs[:] = [d for d in dirs if d not in ("target", ".git")]
        for fn in sorted(files):
            if not fn.endswith(".rs"):
                continue
            try:
                with open(os.path.join(root, fn), "r", encoding="utf-8", errors="replace") as f:
                    code = f.read()
            except OSError:
                continue
            for pat in patterns:
                m = re.search(pat, code)
                if m:
                    app_id, app_id_file = m.group(1), os.path.relpath(os.path.join(root, fn), folder)
                    break
            if app_id:
                break
        if app_id:
            break

    # Symbol suchen: assets/ neben der .rs-Datei, assets/, src/assets/
    icon = ""
    dirs_to_check = [os.path.join(folder, os.path.dirname(bin_path), "assets"),
                     os.path.join(folder, "assets"), os.path.join(folder, "src", "assets"), folder]
    for d in dirs_to_check:
        if not os.path.isdir(d):
            continue
        pngs = sorted(f for f in os.listdir(d) if f.lower().endswith(".png"))
        if not pngs:
            continue
        pref = [f for f in pngs if os.path.splitext(f)[0].lower() in
                (bin_name.lower(), "icon", "logo", "app")]
        icon = os.path.join(d, (pref or pngs)[0])
        break

    import shutil
    return {
        "bin": bin_name, "version": version, "description": description,
        "app_id": app_id, "app_id_file": app_id_file, "icon": icon,
        "has_cargo": bool(find_tool("cargo")),
        "has_zigbuild": bool(find_tool("cargo-zigbuild")),
    }


# ----------------------------------------------------------------------
#  Einstellungen merken (pro Projekt-Datei)
# ----------------------------------------------------------------------
def load_cfg():
    try:
        with open(CFG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cfg(data):
    try:
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ----------------------------------------------------------------------
#  Oberfläche
# ----------------------------------------------------------------------
class BuilderApp:
    def __init__(self, root):
        global LANG
        self.root = root
        self.cfg = load_cfg()
        LANG = detect_language(self.cfg.get("_lang", ""))
        self.proc = None
        self.q = queue.Queue()
        self.main_path = ""
        self.mode = "python"          # "python" oder "rust"
        self.rust_info = {}
        self.expected_out = ""
        self.status_key = ("st_ready", {})

        root.title(APP_TITLE)
        root.geometry("900x960")
        root.minsize(760, 760)
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll()

    # ---------- Aufbau ----------
    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)
        self.main_frame = main

        # --- Sprachauswahl ---
        lr = ttk.Frame(main)
        lr.pack(fill="x", pady=(0, 4))
        def sort_key(c):
            import unicodedata
            n = unicodedata.normalize("NFD", TRANSLATIONS[c].get("_name", c))
            return "".join(ch for ch in n if not unicodedata.combining(ch)).lower()
        self.lang_codes = sorted(TRANSLATIONS, key=sort_key)
        names = [TRANSLATIONS[c].get("_name", c) for c in self.lang_codes]
        self.v_lang = tk.StringVar(value=TRANSLATIONS[LANG].get("_name", LANG))
        cb = ttk.Combobox(lr, textvariable=self.v_lang, values=names, state="readonly", width=14)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", self._on_lang_selected)
        ttk.Label(lr, text=tr("language")).pack(side="right", padx=6)

        # --- Programm ---
        f1 = ttk.LabelFrame(main, text=tr("frm_program"), padding=8)
        f1.pack(fill="x")
        f1.columnconfigure(1, weight=1)

        ttk.Label(f1, text=tr("lbl_project")).grid(row=0, column=0, sticky="w", **pad)
        self.v_main = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_main, state="readonly").grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(f1, text=tr("btn_choose"), command=self.choose_main).grid(row=0, column=2, **pad)

        ttk.Label(f1, text=tr("lbl_folder")).grid(row=1, column=0, sticky="w", **pad)
        self.v_folder = tk.StringVar(value="–")
        ttk.Label(f1, textvariable=self.v_folder, foreground="#555").grid(row=1, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(f1, text=tr("lbl_name")).grid(row=2, column=0, sticky="w", **pad)
        self.v_name = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_name).grid(row=2, column=1, sticky="ew", **pad)

        ttk.Label(f1, text=tr("lbl_icon")).grid(row=3, column=0, sticky="w", **pad)
        self.v_icon = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_icon).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(f1, text="...", width=4, command=self.choose_icon).grid(row=3, column=2, **pad)

        ttk.Label(f1, text=tr("lbl_category")).grid(row=4, column=0, sticky="w", **pad)
        self.v_cat = tk.StringVar(value="Utility;")
        ttk.Combobox(f1, textvariable=self.v_cat, values=CATEGORIES, width=18).grid(row=4, column=1, sticky="w", **pad)

        # Bereich, der je nach Modus (Python / Rust) wechselt
        self.area = ttk.Frame(main)
        self.area.pack(fill="x")

        # --- Pakete ---
        f2 = ttk.LabelFrame(self.area, text=tr("frm_packages"), padding=8)
        f2.pack(fill="x", pady=(8, 0))
        f2.columnconfigure(1, weight=1)
        ttk.Label(f2, text="PACKAGES:").grid(row=0, column=0, sticky="w", **pad)
        self.v_packages = tk.StringVar()
        ttk.Entry(f2, textvariable=self.v_packages).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(f2, text=tr("btn_redetect"), command=self.reanalyze).grid(row=0, column=2, **pad)
        self.lbl_analysis = ttk.Label(f2, text=tr("no_file"), foreground="#555",
                                      justify="left", wraplength=820)
        self.lbl_analysis.grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        # --- Optionen ---
        f3 = ttk.LabelFrame(self.area, text=tr("frm_options"), padding=8)
        f3.pack(fill="x", pady=(8, 0))
        self.v_clean = tk.BooleanVar(value=True)
        self.v_strip = tk.BooleanVar(value=True)
        self.v_target = tk.BooleanVar(value=True)
        self.v_integrate = tk.BooleanVar(value=True)
        self.v_glibc_on = tk.BooleanVar(value=True)
        self.v_glibc = tk.StringVar(value="2.17")
        ttk.Checkbutton(f3, text=tr("opt_clean"),
                        variable=self.v_clean).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text=tr("opt_strip"),
                        variable=self.v_strip).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text=tr("opt_target"),
                        variable=self.v_target).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text=tr("opt_integrate"),
                        variable=self.v_integrate).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text=tr("opt_glibc"),
                        variable=self.v_glibc_on).grid(row=4, column=0, sticky="w")
        ttk.Entry(f3, textvariable=self.v_glibc, width=6).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(f3, text=tr("opt_glibc_hint"), foreground="#555",
                  wraplength=820, justify="left").grid(row=5, column=0, columnspan=3, sticky="w", padx=(22, 0))

        # --- Erweitert ---
        f4 = ttk.LabelFrame(self.area, text=tr("frm_advanced"), padding=8)
        f4.pack(fill="x", pady=(8, 0))
        f4.columnconfigure(1, weight=1)
        ttk.Label(f4, text=tr("lbl_pyver")).grid(row=0, column=0, sticky="w", **pad)
        self.v_pyver = tk.StringVar(value="3.11")
        ttk.Combobox(f4, textvariable=self.v_pyver, values=["3.10", "3.11", "3.12", "3.13"],
                     width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(f4, text=tr("lbl_pysrc")).grid(row=1, column=0, sticky="w", **pad)
        self.v_pysrc = tk.StringVar(value="auto")
        ttk.Combobox(f4, textvariable=self.v_pysrc, values=["auto", "conda", "uv"], state="readonly",
                     width=8).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(f4, text=tr("lbl_data")).grid(row=2, column=0, sticky="w", **pad)
        self.v_data = tk.StringVar(value="*.png *.jpg *.jpeg *.gif *.svg *.ico *.wav *.mp3 *.ogg *.json *.ttf *.otf")
        ttk.Entry(f4, textvariable=self.v_data).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(f4, text=tr("lbl_collect")).grid(row=3, column=0, sticky="w", **pad)
        self.v_collect = tk.StringVar()
        ttk.Entry(f4, textvariable=self.v_collect).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(f4, text=tr("lbl_script")).grid(row=4, column=0, sticky="w", **pad)
        self.v_script = tk.StringVar(value=_existing_script(self.cfg.get("_script"), DEFAULT_SCRIPT))
        ttk.Entry(f4, textvariable=self.v_script).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Button(f4, text="...", width=4, command=self.choose_script).grid(row=4, column=2, **pad)

        self.py_frames = [f2, f3, f4]

        # --- Rust (nur sichtbar, wenn eine Cargo.toml gewählt ist) ---
        fr = ttk.LabelFrame(self.area, text=tr("frm_rust"), padding=8)
        fr.columnconfigure(1, weight=1)
        self.rust_frame = fr
        ttk.Label(fr, text=tr("lbl_appid")).grid(row=0, column=0, sticky="w", **pad)
        self.v_r_appid = tk.StringVar()
        ttk.Entry(fr, textvariable=self.v_r_appid).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr, text=tr("lbl_comment")).grid(row=1, column=0, sticky="w", **pad)
        self.v_r_comment = tk.StringVar()
        ttk.Entry(fr, textvariable=self.v_r_comment).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr, text=tr("lbl_rglibc")).grid(row=2, column=0, sticky="w", **pad)
        self.v_r_glibc = tk.StringVar(value="2.28")
        ttk.Combobox(fr, textvariable=self.v_r_glibc, values=GLIBC_CHOICES, width=8).grid(
            row=2, column=1, sticky="w", **pad)
        ttk.Label(fr, text=tr("rglibc_hint"), foreground="#555", wraplength=640,
                  justify="left").grid(row=3, column=1, columnspan=2, sticky="w", padx=6)
        ttk.Checkbutton(fr, text=tr("opt_integrate"),
                        variable=self.v_integrate).grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        self.lbl_rust = ttk.Label(fr, text="", foreground="#555", justify="left", wraplength=820)
        self.lbl_rust.grid(row=5, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(fr, text=tr("lbl_rscript")).grid(row=7, column=0, sticky="w", **pad)
        self.v_rscript = tk.StringVar(value=_existing_script(self.cfg.get("_rust_script"), DEFAULT_RUST_SCRIPT))
        ttk.Entry(fr, textvariable=self.v_rscript).grid(row=7, column=1, sticky="ew", **pad)
        ttk.Button(fr, text="...", width=4, command=self.choose_rscript).grid(row=7, column=2, **pad)

        # --- Knöpfe ---
        fb = ttk.Frame(main)
        fb.pack(fill="x", pady=8)
        self.btn_build = ttk.Button(fb, text=tr("btn_build"), command=self.start_build, state="disabled")
        self.btn_build.pack(side="left", padx=3)
        self.btn_cancel = ttk.Button(fb, text=tr("btn_cancel"), command=self.cancel_build, state="disabled")
        self.btn_cancel.pack(side="left", padx=3)
        self.btn_dist = ttk.Button(fb, text=tr("btn_dist"), command=self.open_dist, state="disabled")
        self.btn_dist.pack(side="left", padx=3)
        self.progress = ttk.Progressbar(fb, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=3)
        self.v_status = tk.StringVar(value=tr(self.status_key[0], **self.status_key[1]))
        ttk.Label(fb, textvariable=self.v_status).pack(side="right", padx=8)

        # --- Ausgabe ---
        fl = ttk.Frame(main)
        fl.pack(fill="both", expand=True)
        self.log = tk.Text(fl, height=14, wrap="word", state="disabled",
                           background="#1e1e1e", foreground="#dcdcdc", insertbackground="white",
                           font=("DejaVu Sans Mono", 9))
        sb = ttk.Scrollbar(fl, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("err", foreground="#ff6b6b")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("head", foreground="#79c0ff")

    # ---------- Sprache wechseln ----------
    def _on_lang_selected(self, _event=None):
        name = self.v_lang.get()
        code = next((c for c in self.lang_codes if TRANSLATIONS[c].get("_name", c) == name), "en")
        self.change_language(code)

    def change_language(self, code):
        """Oberfläche in einer anderen Sprache neu aufbauen – alle Eingaben,
        die Ausgabe und ein laufender Build bleiben erhalten."""
        global LANG
        if code == LANG or code not in TRANSLATIONS:
            return
        LANG = code
        self.cfg["_lang"] = code
        save_cfg(self.cfg)

        state = self._collect()
        scripts = (self.v_script.get(), self.v_rscript.get())
        main_info = (self.v_main.get(), self.v_folder.get())
        log_dump = self.log.dump("1.0", "end-1c", text=True, tag=True)
        mode, running = self.mode, self.proc is not None

        self.main_frame.destroy()
        self._build_ui()

        self._apply(state)
        self.v_script.set(scripts[0]); self.v_rscript.set(scripts[1])
        self.v_main.set(main_info[0]); self.v_folder.set(main_info[1])
        self._restore_log(log_dump)
        self.set_mode(mode)
        if self.main_path:
            if mode == "rust":
                self.show_rust_info()
            else:
                self.reanalyze(keep_packages=True)
            self.btn_dist.config(state="normal")
            self.btn_build.config(state="disabled" if running else "normal")
        if running:
            self.btn_cancel.config(state="normal")
            self.progress.start(12)

    def _restore_log(self, dump):
        """Ausgabe samt Farben in das neue Textfeld übernehmen."""
        tags = set()
        self.log.configure(state="normal")
        for kind, value, _index in dump:
            if kind == "tagon" and value != "sel":
                tags.add(value)
            elif kind == "tagoff":
                tags.discard(value)
            elif kind == "text":
                self.log.insert("end", value, tuple(tags))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, key, **kw):
        self.status_key = (key, kw)
        self.v_status.set(tr(key, **kw))

    # ---------- Hilfen ----------
    def _start_dir(self):
        d = self.cfg.get("_last_dir", "")
        if d and os.path.isdir(d) and "/.mount_" not in d and "/_MEI" not in d:
            return d
        return os.path.expanduser("~")

    def _log(self, text, tag=None):
        # Farbige Emojis aus der Build-Ausgabe ersetzen: Tk kann sonst auf
        # älteren Systemen (libXft < 2.3.5) abstürzen.
        text = (text.replace("✅", "[OK]").replace("❌", "[X]")
                    .replace("⚠️", "[!]").replace("⚠", "[!]"))
        text = "".join(ch if ord(ch) < 0x1F000 else "?" for ch in text)
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- Auswahl ----------
    def choose_main(self):
        p = filedialog.askopenfilename(title=tr("dlg_main"),
                                       initialdir=self._start_dir(),
                                       filetypes=[(tr("ft_py_or_rust"), "*.py *.pyw Cargo.toml"),
                                                  (tr("ft_python"), "*.py *.pyw"),
                                                  (tr("ft_rust"), "Cargo.toml"),
                                                  (tr("ft_all"), "*")])
        if not p:
            return
        p = os.path.abspath(p)
        self.cfg["_last_dir"] = os.path.dirname(p)
        save_cfg(self.cfg)
        self.load_main(p)

    def set_mode(self, mode):
        self.mode = mode
        if mode == "rust":
            for f in self.py_frames:
                f.pack_forget()
            self.rust_frame.pack(fill="x", pady=(8, 0))
        else:
            self.rust_frame.pack_forget()
            for f in self.py_frames:
                f.pack(fill="x", pady=(8, 0))

    def load_main(self, p):
        self.main_path = p
        folder = os.path.dirname(p)
        name = os.path.splitext(os.path.basename(p))[0]
        self.v_main.set(os.path.basename(p))
        self.v_folder.set(folder)
        if not self.proc:                # alte Meldungen eines anderen Projekts entfernen
            self._clear_log()

        if os.path.basename(p) == "Cargo.toml":
            self.set_mode("rust")
            r = self.rust_info = analyze_rust(p)
            saved = self.cfg.get(p)
            if saved:
                self._apply(saved)
                self._log(tr("log_loaded", name=os.path.basename(folder)) + "\n", "head")
            else:
                self.v_name.set(r["bin"])
                self.v_icon.set(r["icon"])
                self.v_cat.set("Utility;")
                self.v_r_appid.set(r["app_id"] or r["bin"].lower())
                self.v_r_comment.set(r["description"] or r["bin"])
                self.v_r_glibc.set("2.28")
                self.v_integrate.set(True)
            self.show_rust_info()
            self.btn_build.config(state="normal")
            self.btn_dist.config(state="normal")
            return

        self.set_mode("python")

        saved = self.cfg.get(p)
        if saved:                                   # früher schon benutzt -> Werte wiederherstellen
            self._apply(saved)
            self._log(tr("log_loaded", name=os.path.basename(p)) + "\n", "head")
        else:
            self.v_name.set(name)
            self.v_icon.set(find_icon(folder, name))
        self.reanalyze(keep_packages=bool(saved))
        self.btn_build.config(state="normal")
        self.btn_dist.config(state="normal")

    def show_rust_info(self):
        r = self.rust_info
        lines = [tr("ru_bin", bin=r["bin"], version=r["version"])]
        if r["app_id"]:
            lines.append(tr("ru_appid_found", file=r["app_id_file"], appid=r["app_id"]))
        else:
            lines.append(tr("ru_appid_missing"))
        if not r["icon"]:
            lines.append(tr("ru_no_icon"))
        if not r["has_cargo"]:
            lines.append(tr("ru_no_cargo"))
        elif not r["has_zigbuild"]:
            lines.append(tr("ru_no_zig"))
        else:
            lines.append(tr("ru_zig_ok"))
        lines.append(tr("ru_result", file=f"{r['bin']}-{r['version']}-x86_64.AppImage"))
        self.lbl_rust.config(text="\n".join(lines))

    def choose_rscript(self):
        start = os.path.dirname(self.v_rscript.get()) if self.v_rscript.get() else HERE
        p = filedialog.askopenfilename(title=tr("dlg_rscript"), initialdir=start,
                                       filetypes=[(tr("ft_shell"), "*.sh"), (tr("ft_all"), "*")])
        if p:
            self.v_rscript.set(os.path.abspath(p))
            self.cfg["_rust_script"] = self.v_rscript.get()
            save_cfg(self.cfg)

    def reanalyze(self, keep_packages=False):
        if not self.main_path:
            return
        if self.mode == "rust":
            self.rust_info = analyze_rust(self.main_path)
            self.show_rust_info()
            return
        r = analyze(self.main_path)
        if not keep_packages:
            self.v_packages.set(" ".join(r["packages"]))
            if not self.cfg.get(self.main_path):
                self.v_cat.set("Game;" if "pygame" in r["packages"] else self.v_cat.get())
        lines = []
        gui = [p for p in r["packages"] if p in GUI_TOOLKITS]
        if gui:
            lines.append(tr("an_gui", names=", ".join(gui)))
        elif r["uses_tk"]:
            lines.append(tr("an_tk"))
        else:
            lines.append(tr("an_no_gui"))
        lines.append(tr("an_packages", names=", ".join(r["packages"]) if r["packages"] else tr("an_none")))
        if r["local"]:
            lines.append(tr("an_local", names=", ".join(r["local"])))
        if r["has_requirements"]:
            lines.append(tr("an_requirements"))
        if not find_tool("uv"):
            lines.append(tr("tool_no_uv"))
        if not find_tool("curl"):
            lines.append(tr("tool_no_curl"))
        for key, kw in r["notes"]:
            lines.append(tr("an_hint", text=tr(key, **kw)))
        for e in r["errors"]:
            lines.append(tr("an_read_error", text=e))
        self.lbl_analysis.config(text="\n".join(lines))

    def choose_icon(self):
        start = os.path.dirname(self.v_icon.get()) if self.v_icon.get() else self._start_dir()
        p = filedialog.askopenfilename(title=tr("dlg_icon"), initialdir=start,
                                       filetypes=[(tr("ft_png"), "*.png"), (tr("ft_all"), "*")])
        if p:
            self.v_icon.set(os.path.abspath(p))

    def choose_script(self):
        start = os.path.dirname(self.v_script.get()) if self.v_script.get() else HERE
        p = filedialog.askopenfilename(title=tr("dlg_script"), initialdir=start,
                                       filetypes=[(tr("ft_shell"), "*.sh"), (tr("ft_all"), "*")])
        if p:
            self.v_script.set(os.path.abspath(p))
            self.cfg["_script"] = self.v_script.get()
            save_cfg(self.cfg)

    # ---------- Einstellungen sammeln / anwenden ----------
    def _collect(self):
        return {
            "name": self.v_name.get().strip(), "icon": self.v_icon.get().strip(),
            "cat": self.v_cat.get().strip(), "packages": self.v_packages.get().strip(),
            "clean": self.v_clean.get(), "strip": self.v_strip.get(), "target": self.v_target.get(),
            "integrate": self.v_integrate.get(), "glibc_on": self.v_glibc_on.get(),
            "glibc": self.v_glibc.get().strip(), "pyver": self.v_pyver.get().strip(),
            "pysrc": self.v_pysrc.get(), "data": self.v_data.get().strip(),
            "collect": self.v_collect.get().strip(),
            "mode": self.mode, "r_appid": self.v_r_appid.get().strip(),
            "r_comment": self.v_r_comment.get().strip(), "r_glibc": self.v_r_glibc.get().strip(),
        }

    def _apply(self, s):
        self.v_name.set(s.get("name", "")); self.v_icon.set(s.get("icon", ""))
        self.v_cat.set(s.get("cat", "Utility;")); self.v_packages.set(s.get("packages", ""))
        self.v_clean.set(s.get("clean", True)); self.v_strip.set(s.get("strip", True))
        self.v_target.set(s.get("target", True)); self.v_integrate.set(s.get("integrate", True))
        self.v_glibc_on.set(s.get("glibc_on", True)); self.v_glibc.set(s.get("glibc", "2.17"))
        self.v_pyver.set(s.get("pyver", "3.11")); self.v_pysrc.set(s.get("pysrc", "auto"))
        self.v_data.set(s.get("data", self.v_data.get())); self.v_collect.set(s.get("collect", ""))
        self.v_r_appid.set(s.get("r_appid", "")); self.v_r_comment.set(s.get("r_comment", ""))
        self.v_r_glibc.set(s.get("r_glibc", "2.28"))

    # ---------- Bauen ----------
    def start_build(self):
        if self.proc:
            return
        s = self._collect()
        if self.mode == "rust":
            job = self._rust_job(s)
            if not job:
                return
            script, env, info = job
            self.expected_out = os.path.join(os.path.dirname(self.main_path), "dist",
                                             f"{self.rust_info['bin']}-{self.rust_info['version']}-x86_64.AppImage")
            self._run(script, env, s, info)
            return
        script = self.v_script.get().strip()
        if not os.path.isfile(script):
            messagebox.showerror(APP_TITLE, tr("err_script", path=script))
            return
        if not find_tool("uv"):
            self.reanalyze(keep_packages=True)          # Hinweis auch im Fenster zeigen
            messagebox.showerror(APP_TITLE, tr("err_no_uv"))
            return
        if not find_tool("curl"):
            messagebox.showerror(APP_TITLE, tr("err_no_curl"))
            return
        if not s["name"]:
            messagebox.showerror(APP_TITLE, tr("err_name"))
            return
        if not os.path.isfile(s["icon"]):
            messagebox.showerror(APP_TITLE, tr("err_icon"))
            return
        if s["glibc_on"]:
            try:
                tuple(int(x) for x in s["glibc"].split("."))
            except ValueError:
                messagebox.showerror(APP_TITLE, tr("err_glibc"))
                return

        self.cfg[self.main_path] = s
        save_cfg(self.cfg)

        env = add_tool_dirs(clean_env())
        env.update({
            "PROJECT_DIR": os.path.dirname(self.main_path),
            "MAIN_SCRIPT": os.path.basename(self.main_path),
            "APP_NAME": s["name"],
            "ICON": s["icon"],
            "CATEGORY": s["cat"] if s["cat"].endswith(";") else s["cat"] + ";",
            "PYTHON_VERSION": s["pyver"],
            "PACKAGES": s["packages"],
            "MAX_GLIBC": s["glibc"] if s["glibc_on"] else "99.99",
            "PYTHON_SOURCE": s["pysrc"],
            "DATA_PATTERNS": s["data"],
            "STRIP_SYSTEM_LIBS": "yes" if s["strip"] else "no",
            "AUTO_INTEGRATE": "yes" if s["integrate"] else "no",
            "TARGET_PLATFORM": "auto" if s["target"] else "",
            "COLLECT": s["collect"],
            "CLEAN_BUILD": "yes" if s["clean"] else "no",
        })

        self.expected_out = os.path.join(os.path.dirname(self.main_path), "dist",
                                         f"{s['name']}-x86_64.AppImage")
        self._run(script, env, s, f"PACKAGES=\"{s['packages']}\"")

    def _rust_job(self, s):
        script = self.v_rscript.get().strip()
        if not os.path.isfile(script):
            messagebox.showerror(APP_TITLE, tr("err_rscript", path=script))
            return None
        if not self.rust_info.get("has_cargo"):
            messagebox.showerror(APP_TITLE, tr("err_no_cargo"))
            return None
        if not s["name"] or not s["r_appid"]:
            messagebox.showerror(APP_TITLE, tr("err_name_appid"))
            return None
        if not os.path.isfile(s["icon"]):
            messagebox.showerror(APP_TITLE, tr("err_icon"))
            return None
        self.cfg[self.main_path] = s
        save_cfg(self.cfg)
        env = add_tool_dirs(clean_env())
        env.update({
            "PROJECT_DIR": os.path.dirname(self.main_path),
            "BIN": self.rust_info["bin"],
            "APP_NAME": s["name"],
            "APP_ID": s["r_appid"],
            "ICON": s["icon"],
            "COMMENT": s["r_comment"],
            "CATEGORY": s["cat"] if s["cat"].endswith(";") else s["cat"] + ";",
            "GLIBC": s["r_glibc"],
            "AUTO_INTEGRATE": "yes" if s["integrate"] else "no",
        })
        return script, env, f"Rust, glibc {s['r_glibc']}, APP_ID {s['r_appid']}"

    def _run(self, script, env, s, info):
        self._clear_log()
        self._log(tr("log_building", name=s["name"], path=self.main_path) + "\n", "head")
        self._log(f"{info}\n", "head")
        if LANG != "de":
            self._log(tr("log_note_lang") + "\n", "head")
        self._log("\n")
        try:
            self.proc = subprocess.Popen(["bash", script], env=env, cwd=os.path.dirname(self.main_path),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, errors="replace",
                                         start_new_session=True)
        except Exception as e:
            self.proc = None
            messagebox.showerror(APP_TITLE, tr("err_start", error=e))
            return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.btn_build.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self._set_status("st_building")
        self.progress.start(12)

    def _reader(self, proc):
        # läuft im Hintergrund: nur in die Warteschlange schreiben, nie Tk anfassen
        for line in proc.stdout:
            self.q.put(("line", line))
        proc.wait()
        self.q.put(("done", proc.returncode))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "line":
                    tag = None
                    if "FEHLER" in val or "❌" in val or "Error" in val:
                        tag = "err"
                    elif val.startswith("==>"):
                        tag = "head"
                    elif "✅" in val or "ERFOLGREICH" in val:
                        tag = "ok"
                    self._log(val, tag)
                else:
                    self._finished(val)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _finished(self, code):
        self.proc = None
        self.progress.stop()
        self.btn_build.config(state="normal")
        self.btn_cancel.config(state="disabled")
        out = self.expected_out
        if code == 0:
            self._set_status("st_done")
            self._log("\n" + tr("log_done", path=out) + "\n", "ok")
            messagebox.showinfo(APP_TITLE, tr("msg_created", path=out))
        elif code in (-signal.SIGTERM, -signal.SIGKILL, 143, 137):
            self._set_status("st_cancelled")
            self._log("\n" + tr("log_cancelled") + "\n", "err")
        else:
            self._set_status("st_error", code=code)
            self._log("\n" + tr("log_failed", code=code) + "\n", "err")
            messagebox.showerror(APP_TITLE, tr("msg_failed"))

    def cancel_build(self):
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)    # ganzes Skript samt Unterprogrammen
            except Exception:
                pass

    def open_dist(self):
        if not self.main_path:
            return
        d = os.path.join(os.path.dirname(self.main_path), "dist")
        if not os.path.isdir(d):
            d = os.path.dirname(self.main_path)
        try:
            subprocess.Popen(["xdg-open", d], start_new_session=True, env=clean_env(),
                             cwd=os.path.expanduser("~"),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showerror(APP_TITLE, tr("err_open", error=e))

    def _on_close(self):
        if self.proc:
            if not messagebox.askyesno(APP_TITLE, tr("ask_quit")):
                return
            self.cancel_build()
        if self.main_path:
            self.cfg[self.main_path] = self._collect()
            save_cfg(self.cfg)
        self.root.destroy()


def main():
    _load_extra_languages()

    # Vorlage für eine neue Sprache ausgeben:
    #   python3 AppImage_Builder.py --export-lang en > lang/es.json
    if "--export-lang" in sys.argv:
        i = sys.argv.index("--export-lang")
        code = sys.argv[i + 1] if i + 1 < len(sys.argv) else "en"
        data = dict(TRANSLATIONS.get(code, TRANSLATIONS["en"]))
        data["_name"] = "NAME DER SPRACHE / LANGUAGE NAME"
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    root = tk.Tk()
    app = BuilderApp(root)
    # Datei beim Start mitgegeben (z. B. "Öffnen mit" oder im Terminal)?
    args = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if args:
        p = os.path.abspath(args[0])
        root.after(100, lambda: app.load_main(p))
    root.mainloop()


if __name__ == "__main__":
    main()
