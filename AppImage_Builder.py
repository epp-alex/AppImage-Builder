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
SYSTEM_ONLY = {"gi": "PyGObject (GTK) – über pip schwierig, besser vermeiden",
               "dbus": "dbus-python – braucht System-Bibliotheken"}

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
    die nicht dazugehören, werden NICHT mitgezählt."""
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
            notes.append(f"{n}: nur unter Windows – wird unter Linux nicht gebraucht/geht nicht")
            continue
        if n in SYSTEM_ONLY:
            notes.append(f"{n}: {SYSTEM_ONLY[n]}")
            continue
        pkg = BELONGS_TO.get(n) or PYPI_NAMES.get(n, n)
        if pkg not in packages:
            packages.append(pkg)

    toolkits = [p for p in packages if p in GUI_TOOLKITS]
    if len(toolkits) > 1:
        notes.append("Mehrere Oberflächen-Bibliotheken gefunden: " + ", ".join(toolkits)
                     + " – meist braucht man nur eine.")
    if "PyQt6" in packages or "PySide2" in packages:
        notes.append("PyQt6/PySide2 sind im Build-Skript nicht besonders berücksichtigt.")

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
        "has_cargo": bool(shutil.which("cargo")),
        "has_zigbuild": bool(shutil.which("cargo-zigbuild")),
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
        self.root = root
        self.cfg = load_cfg()
        self.proc = None
        self.q = queue.Queue()
        self.main_path = ""
        self.mode = "python"          # "python" oder "rust"
        self.rust_info = {}
        self.expected_out = ""

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

        # --- Programm ---
        f1 = ttk.LabelFrame(main, text="Programm", padding=8)
        f1.pack(fill="x")
        f1.columnconfigure(1, weight=1)

        ttk.Label(f1, text="Projektdatei:").grid(row=0, column=0, sticky="w", **pad)
        self.v_main = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_main, state="readonly").grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(f1, text="Auswählen ...", command=self.choose_main).grid(row=0, column=2, **pad)

        ttk.Label(f1, text="Ordner:").grid(row=1, column=0, sticky="w", **pad)
        self.v_folder = tk.StringVar(value="–")
        ttk.Label(f1, textvariable=self.v_folder, foreground="#555").grid(row=1, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(f1, text="Programmname:").grid(row=2, column=0, sticky="w", **pad)
        self.v_name = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_name).grid(row=2, column=1, sticky="ew", **pad)

        ttk.Label(f1, text="Symbol (PNG):").grid(row=3, column=0, sticky="w", **pad)
        self.v_icon = tk.StringVar()
        ttk.Entry(f1, textvariable=self.v_icon).grid(row=3, column=1, sticky="ew", **pad)
        ttk.Button(f1, text="...", width=4, command=self.choose_icon).grid(row=3, column=2, **pad)

        ttk.Label(f1, text="Kategorie:").grid(row=4, column=0, sticky="w", **pad)
        self.v_cat = tk.StringVar(value="Utility;")
        ttk.Combobox(f1, textvariable=self.v_cat, values=CATEGORIES, width=18).grid(row=4, column=1, sticky="w", **pad)

        # Bereich, der je nach Modus (Python / Rust) wechselt
        self.area = ttk.Frame(main)
        self.area.pack(fill="x")

        # --- Pakete ---
        f2 = ttk.LabelFrame(self.area, text="Pakete (aus den Importen erkannt, änderbar)", padding=8)
        f2.pack(fill="x", pady=(8, 0))
        f2.columnconfigure(1, weight=1)
        ttk.Label(f2, text="PACKAGES:").grid(row=0, column=0, sticky="w", **pad)
        self.v_packages = tk.StringVar()
        ttk.Entry(f2, textvariable=self.v_packages).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(f2, text="Neu erkennen", command=self.reanalyze).grid(row=0, column=2, **pad)
        self.lbl_analysis = ttk.Label(f2, text="Noch keine Datei ausgewählt.", foreground="#555",
                                      justify="left", wraplength=820)
        self.lbl_analysis.grid(row=1, column=0, columnspan=3, sticky="w", **pad)

        # --- Optionen ---
        f3 = ttk.LabelFrame(self.area, text="Optionen", padding=8)
        f3.pack(fill="x", pady=(8, 0))
        self.v_clean = tk.BooleanVar(value=True)
        self.v_strip = tk.BooleanVar(value=True)
        self.v_target = tk.BooleanVar(value=True)
        self.v_integrate = tk.BooleanVar(value=True)
        self.v_glibc_on = tk.BooleanVar(value=True)
        self.v_glibc = tk.StringVar(value="2.17")
        ttk.Checkbutton(f3, text="Komplett neu bauen (Python-Umgebung frisch anlegen)",
                        variable=self.v_clean).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text="System-Bibliotheken nicht einpacken (läuft auch auf älteren Linux)",
                        variable=self.v_strip).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text="Pakete in der Ausgabe für ältere Systeme wählen (empfohlen)",
                        variable=self.v_target).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text="Beim ersten Start mit Symbol ins Startmenü eintragen",
                        variable=self.v_integrate).grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(f3, text="glibc-Prüfung: Build abbrechen, wenn mehr nötig als",
                        variable=self.v_glibc_on).grid(row=4, column=0, sticky="w")
        ttk.Entry(f3, textvariable=self.v_glibc, width=6).grid(row=4, column=1, sticky="w", padx=4)
        ttk.Label(f3, text="(2.17 = fast jedes Linux; PySide6 hebt auf 2.34 an)",
                  foreground="#555").grid(row=4, column=2, sticky="w")

        # --- Erweitert ---
        f4 = ttk.LabelFrame(self.area, text="Erweitert", padding=8)
        f4.pack(fill="x", pady=(8, 0))
        f4.columnconfigure(1, weight=1)
        ttk.Label(f4, text="Python-Version:").grid(row=0, column=0, sticky="w", **pad)
        self.v_pyver = tk.StringVar(value="3.11")
        ttk.Combobox(f4, textvariable=self.v_pyver, values=["3.10", "3.11", "3.12", "3.13"],
                     width=8).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(f4, text="Python-Quelle:").grid(row=1, column=0, sticky="w", **pad)
        self.v_pysrc = tk.StringVar(value="auto")
        ttk.Combobox(f4, textvariable=self.v_pysrc, values=["auto", "conda", "uv"], state="readonly",
                     width=8).grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(f4, text="Datendateien:").grid(row=2, column=0, sticky="w", **pad)
        self.v_data = tk.StringVar(value="*.png *.jpg *.jpeg *.gif *.svg *.ico *.wav *.mp3 *.ogg *.json *.ttf *.otf")
        ttk.Entry(f4, textvariable=self.v_data).grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(f4, text="Komplett einpacken:").grid(row=3, column=0, sticky="w", **pad)
        self.v_collect = tk.StringVar()
        ttk.Entry(f4, textvariable=self.v_collect).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(f4, text="Build-Skript:").grid(row=4, column=0, sticky="w", **pad)
        self.v_script = tk.StringVar(value=_existing_script(self.cfg.get("_script"), DEFAULT_SCRIPT))
        ttk.Entry(f4, textvariable=self.v_script).grid(row=4, column=1, sticky="ew", **pad)
        ttk.Button(f4, text="...", width=4, command=self.choose_script).grid(row=4, column=2, **pad)

        self.py_frames = [f2, f3, f4]

        # --- Rust (nur sichtbar, wenn eine Cargo.toml gewählt ist) ---
        fr = ttk.LabelFrame(self.area, text="Rust-Programm", padding=8)
        fr.columnconfigure(1, weight=1)
        self.rust_frame = fr
        ttk.Label(fr, text="Kennung (APP_ID):").grid(row=0, column=0, sticky="w", **pad)
        self.v_r_appid = tk.StringVar()
        ttk.Entry(fr, textvariable=self.v_r_appid).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr, text="Beschreibung:").grid(row=1, column=0, sticky="w", **pad)
        self.v_r_comment = tk.StringVar()
        ttk.Entry(fr, textvariable=self.v_r_comment).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr, text="Älteste glibc:").grid(row=2, column=0, sticky="w", **pad)
        self.v_r_glibc = tk.StringVar(value="2.28")
        gl = ttk.Frame(fr)
        gl.grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Combobox(gl, textvariable=self.v_r_glibc, values=GLIBC_CHOICES, width=8).pack(side="left")
        ttk.Label(gl, text="  (2.17 = fast jedes Linux, 2.28 = ab Mint 20 / Ubuntu 20.04 / Debian 10)",
                  foreground="#555").pack(side="left")
        ttk.Checkbutton(fr, text="Beim ersten Start mit Symbol ins Startmenü eintragen",
                        variable=self.v_integrate).grid(row=3, column=0, columnspan=3, sticky="w", **pad)
        self.lbl_rust = ttk.Label(fr, text="", foreground="#555", justify="left", wraplength=820)
        self.lbl_rust.grid(row=4, column=0, columnspan=3, sticky="w", **pad)
        ttk.Label(fr, text="Rust-Build-Skript:").grid(row=5, column=0, sticky="w", **pad)
        self.v_rscript = tk.StringVar(value=_existing_script(self.cfg.get("_rust_script"), DEFAULT_RUST_SCRIPT))
        ttk.Entry(fr, textvariable=self.v_rscript).grid(row=5, column=1, sticky="ew", **pad)
        ttk.Button(fr, text="...", width=4, command=self.choose_rscript).grid(row=5, column=2, **pad)

        # --- Knöpfe ---
        fb = ttk.Frame(main)
        fb.pack(fill="x", pady=8)
        self.btn_build = ttk.Button(fb, text="AppImage bauen", command=self.start_build, state="disabled")
        self.btn_build.pack(side="left", padx=3)
        self.btn_cancel = ttk.Button(fb, text="Abbrechen", command=self.cancel_build, state="disabled")
        self.btn_cancel.pack(side="left", padx=3)
        self.btn_dist = ttk.Button(fb, text="dist-Ordner öffnen", command=self.open_dist, state="disabled")
        self.btn_dist.pack(side="left", padx=3)
        self.progress = ttk.Progressbar(fb, mode="indeterminate", length=180)
        self.progress.pack(side="right", padx=3)
        self.v_status = tk.StringVar(value="Bereit")
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

    # ---------- Hilfen ----------
    def _start_dir(self):
        d = self.cfg.get("_last_dir", "")
        if d and os.path.isdir(d) and "/.mount_" not in d and "/_MEI" not in d:
            return d
        return os.path.expanduser("~")

    def _log(self, text, tag=None):
        # Farbige Emojis aus der Build-Ausgabe ersetzen: Tk kann sonst auf
        # älteren Systemen (libXft < 2.3.5) abstürzen.
        text = (text.replace("\u2705", "[OK]").replace("\u274c", "[X]")
                    .replace("\u26a0\ufe0f", "[!]").replace("\u26a0", "[!]"))
        text = "".join(ch if ord(ch) < 0x1F000 else "?" for ch in text)
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- Auswahl ----------
    def choose_main(self):
        p = filedialog.askopenfilename(title="Python-Hauptdatei oder Cargo.toml wählen",
                                       initialdir=self._start_dir(),
                                       filetypes=[("Python oder Rust", "*.py *.pyw Cargo.toml"),
                                                  ("Python", "*.py *.pyw"), ("Rust (Cargo.toml)", "Cargo.toml"),
                                                  ("Alle Dateien", "*")])
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

        if os.path.basename(p) == "Cargo.toml":
            self.set_mode("rust")
            r = self.rust_info = analyze_rust(p)
            saved = self.cfg.get(p)
            if saved:
                self._apply(saved)
                self._log(f"Gespeicherte Einstellungen für {os.path.basename(folder)} geladen.\n", "head")
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
            self._log(f"Gespeicherte Einstellungen für {os.path.basename(p)} geladen.\n", "head")
        else:
            self.v_name.set(name)
            self.v_icon.set(find_icon(folder, name))
        self.reanalyze(keep_packages=bool(saved))
        self.btn_build.config(state="normal")
        self.btn_dist.config(state="normal")

    def show_rust_info(self):
        r = self.rust_info
        lines = [f"Programmdatei: {r['bin']}    Version: {r['version']}"]
        if r["app_id"]:
            lines.append(f"APP_ID im Quelltext gefunden ({r['app_id_file']}): {r['app_id']}")
        else:
            lines.append("Keine APP_ID im Quelltext gefunden – Kennung bitte prüfen "
                         "(sie muss zur Fenster-Kennung im Programm passen).")
        if not r["icon"]:
            lines.append("Kein PNG-Symbol gefunden – bitte oben auswählen.")
        if not r["has_cargo"]:
            lines.append("WARNUNG: cargo nicht gefunden – Rust ist auf diesem Rechner nicht installiert.")
        elif not r["has_zigbuild"]:
            lines.append("WARNUNG: cargo-zigbuild fehlt – die glibc-Einstellung wirkt dann nicht. "
                         "Installieren: cargo install cargo-zigbuild && pip install ziglang")
        else:
            lines.append("cargo-zigbuild vorhanden – baut für die gewählte glibc.")
        lines.append(f"Ergebnis: dist/{r['bin']}-{r['version']}-x86_64.AppImage")
        self.lbl_rust.config(text="\n".join(lines))

    def choose_rscript(self):
        start = os.path.dirname(self.v_rscript.get()) if self.v_rscript.get() else HERE
        p = filedialog.askopenfilename(title="build_appimage_rust.sh wählen", initialdir=start,
                                       filetypes=[("Shell-Skript", "*.sh"), ("Alle Dateien", "*")])
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
            lines.append("Oberfläche: " + ", ".join(gui))
        elif r["uses_tk"]:
            lines.append("Oberfläche: Tkinter (schon in Python enthalten, kein Paket nötig)")
        else:
            lines.append("Keine Oberflächen-Bibliothek gefunden.")
        lines.append("Erkannte Pakete: " + (", ".join(r["packages"]) if r["packages"] else "keine"))
        if r["local"]:
            lines.append("Eigene Module (werden mit eingepackt): " + ", ".join(r["local"]))
        if r["has_requirements"]:
            lines.append("requirements.txt gefunden – wird zusätzlich installiert.")
        for n in r["notes"]:
            lines.append("Hinweis: " + n)
        for e in r["errors"]:
            lines.append("Fehler beim Lesen: " + e)
        self.lbl_analysis.config(text="\n".join(lines))

    def choose_icon(self):
        start = os.path.dirname(self.v_icon.get()) if self.v_icon.get() else self._start_dir()
        p = filedialog.askopenfilename(title="Symbol wählen", initialdir=start,
                                       filetypes=[("PNG-Bild", "*.png"), ("Alle Dateien", "*")])
        if p:
            self.v_icon.set(os.path.abspath(p))

    def choose_script(self):
        start = os.path.dirname(self.v_script.get()) if self.v_script.get() else HERE
        p = filedialog.askopenfilename(title="build_appimage_v2.sh wählen", initialdir=start,
                                       filetypes=[("Shell-Skript", "*.sh"), ("Alle Dateien", "*")])
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
            messagebox.showerror(APP_TITLE, f"Build-Skript nicht gefunden:\n{script}\n\n"
                                 "Unter 'Erweitert' auswählen.")
            return
        if not s["name"]:
            messagebox.showerror(APP_TITLE, "Bitte einen Programmnamen eingeben.")
            return
        if not os.path.isfile(s["icon"]):
            messagebox.showerror(APP_TITLE, "Bitte ein Symbol (PNG-Datei) auswählen.")
            return
        if s["glibc_on"]:
            try:
                tuple(int(x) for x in s["glibc"].split("."))
            except ValueError:
                messagebox.showerror(APP_TITLE, "glibc-Grenze bitte als Zahl wie 2.17 eingeben.")
                return

        self.cfg[self.main_path] = s
        save_cfg(self.cfg)

        env = clean_env()
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
            messagebox.showerror(APP_TITLE, f"Rust-Build-Skript nicht gefunden:\n{script}\n\n"
                                 "Im Bereich 'Rust-Programm' auswählen.")
            return None
        if not self.rust_info.get("has_cargo"):
            messagebox.showerror(APP_TITLE, "cargo wurde nicht gefunden. Ist Rust installiert?")
            return None
        if not s["name"] or not s["r_appid"]:
            messagebox.showerror(APP_TITLE, "Bitte Programmname und Kennung (APP_ID) eingeben.")
            return None
        if not os.path.isfile(s["icon"]):
            messagebox.showerror(APP_TITLE, "Bitte ein Symbol (PNG-Datei) auswählen.")
            return None
        self.cfg[self.main_path] = s
        save_cfg(self.cfg)
        env = clean_env()
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
        self.log.configure(state="normal"); self.log.delete("1.0", "end"); self.log.configure(state="disabled")
        self._log(f"Baue {s['name']} aus {self.main_path}\n", "head")
        self._log(f"{info}\n\n", "head")
        try:
            self.proc = subprocess.Popen(["bash", script], env=env, cwd=os.path.dirname(self.main_path),
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, errors="replace",
                                         start_new_session=True)
        except Exception as e:
            self.proc = None
            messagebox.showerror(APP_TITLE, f"Konnte das Build-Skript nicht starten:\n{e}")
            return
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.btn_build.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.v_status.set("Baue ...")
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
            self.v_status.set("Fertig")
            self._log(f"\nFertig: {out}\n", "ok")
            messagebox.showinfo(APP_TITLE, f"AppImage erstellt:\n{out}")
        elif code in (-signal.SIGTERM, -signal.SIGKILL, 143, 137):
            self.v_status.set("Abgebrochen")
            self._log("\nAbgebrochen.\n", "err")
        else:
            self.v_status.set(f"Fehler (Code {code})")
            self._log(f"\nBuild fehlgeschlagen (Code {code}). Siehe Ausgabe oben.\n", "err")
            messagebox.showerror(APP_TITLE, "Build fehlgeschlagen. Details stehen in der Ausgabe.")

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
            messagebox.showerror(APP_TITLE, f"Ordner konnte nicht geöffnet werden:\n{e}")

    def _on_close(self):
        if self.proc:
            if not messagebox.askyesno(APP_TITLE, "Es läuft noch ein Build. Abbrechen und beenden?"):
                return
            self.cancel_build()
        if self.main_path:
            self.cfg[self.main_path] = self._collect()
            save_cfg(self.cfg)
        self.root.destroy()


def main():
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
