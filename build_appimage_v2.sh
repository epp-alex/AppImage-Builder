#!/usr/bin/env bash
# ======================================================================
#  build_appimage.sh – macht aus Python-Dateien + Bildern ein AppImage
#
#  Einfach in den Ordner mit deinen .py- und .png-Dateien legen und
#  ausführen:
#
#      bash build_appimage.sh
#      bash build_appimage.sh --clean   # kompletter Neuaufbau
#
#  Ergebnis:  dist/<APP_NAME>-x86_64.AppImage
# ======================================================================
set -euo pipefail

# --clean erzwingt einen vollständigen Neuaufbau der Build-Umgebung.
CLEAN_BUILD="${CLEAN_BUILD-yes}"
if [[ "${1:-}" == "--clean" ]]; then
    CLEAN_BUILD="yes"
elif [[ $# -gt 0 ]]; then
    echo "FEHLER: Unbekannte Option: $1"
    echo "Verwendung: bash build_appimage.sh [--clean]"
    exit 1
fi

# ======================= EINSTELLUNGEN ================================
# Jede Einstellung kann auch von außen gesetzt werden (z. B. vom
# AppImage-Builder mit Oberfläche): APP_NAME="X" bash build_appimage_v2.sh
APP_NAME="${APP_NAME-Tetris}"
MAIN_SCRIPT="${MAIN_SCRIPT-Tetris.py}"
ICON="${ICON-icon.png}"                # Programm-Icon (PNG, am besten 256x256)
CATEGORY="${CATEGORY-Education;}"          # Startmenü-Kategorie (Education, Game, Office, ...)
PYTHON_VERSION="${PYTHON_VERSION-3.11}"
# PyPI-Paketversionen möglichst festlegen, damit Builds reproduzierbar bleiben.
# Beispiel: "PyQt5==5.15.11"
PACKAGES="${PACKAGES-PyQt5==5.15.11}"
# Maximale erlaubte glibc-Version für das Zielsystem.
# 2.17 = sehr gute Rückwärtskompatibilität für x86_64 Linux.
MAX_GLIBC="${MAX_GLIBC-2.17}"
# Woher Python kommt:
#   "auto"  = bei Tkinter-Programmen conda-forge (Tk MIT geglätteter Schrift
#             und Emoji), sonst uv. Empfohlen.
#   "uv"    = portables Python von uv (Tk OHNE Xft: kantige Schrift!)
#   "conda" = immer conda-forge
PYTHON_SOURCE="${PYTHON_SOURCE-auto}"
                               #   PySide6-Programm:  "PySide6"
                               #   PyQt5-Programm:    "PyQt5==5.15.11"
                               #   Tkinter-Programm:  ""   (Tkinter ist schon in Python)
                               # mehrere mit Leerzeichen: "PySide6 numpy"
# Dateitypen, die als Programmdateien mit eingepackt werden:
DATA_PATTERNS="${DATA_PATTERNS-*.png *.jpg *.jpeg *.gif *.svg *.ico *.wav *.mp3 *.ogg *.json *.ttf *.otf}"
# System-Bibliotheken des Build-Rechners NICHT einpacken (GTK, X11, GLib ...).
# Die hat jeder Linux-Desktop selbst. Dadurch läuft das AppImage auch auf
# älteren Systemen. Mindest-glibc (wird am Ende angezeigt):
#   PySide6: 2.34 (Mint 21, Ubuntu 22.04, Debian 12)
#   PyQt5 / Tkinter: 2.17 (praktisch jedes Linux der letzten 10 Jahre)
STRIP_SYSTEM_LIBS="${STRIP_SYSTEM_LIBS-yes}"
# Beim ersten Start selbst ins Startmenü eintragen (mit Symbol).
#   "yes" = automatisch   "no" = nie
AUTO_INTEGRATE="${AUTO_INTEGRATE-yes}"
# Pakete nur in der Ausgabe für ältere Systeme installieren.
#   "auto"  = PySide6: glibc 2.34, sonst glibc 2.17 (empfohlen)
#   ""      = immer die neueste Ausgabe (kann die glibc-Grenze erhöhen)
#   oder fest, z. B. "x86_64-manylinux_2_28"
TARGET_PLATFORM="${TARGET_PLATFORM-auto}"
# Module, die PyInstaller komplett einpacken soll, weil sie Teile erst beim
# Start nachladen (mehrere mit Leerzeichen). pynput wird automatisch erkannt.
COLLECT="${COLLECT-}"
# Pakete, die auf diesem Rechner kompiliert werden DÜRFEN, weil es sie nicht
# fertig gibt und sie die glibc-Grenze nicht anheben (evdev braucht nur 2.4).
# evdev wird bei pynput automatisch ergänzt.
BUILD_FROM_SOURCE="${BUILD_FROM_SOURCE-}"
# ======================================================================

# Projektordner: Ordner des Skripts, oder von außen vorgegeben (PROJECT_DIR)
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$(readlink -f "$0")")}"
cd "$PROJECT_DIR"
PROJECT_DIR="$(pwd)"
# Icon darf auch außerhalb des Projektordners liegen (absoluter Pfad)
[[ "$ICON" = /* ]] || ICON="$PROJECT_DIR/$ICON"

echo "==> Prüfe System ..."

HOST_ARCH="$(uname -m)"
if [[ "$HOST_ARCH" != "x86_64" ]]; then
    echo "FEHLER: Dieses Script benötigt ein x86_64-System. Gefunden: $HOST_ARCH"
    exit 1
fi

command -v curl >/dev/null || {
    echo "FEHLER: curl nicht gefunden."
    exit 1
}

echo "    Architektur: $HOST_ARCH"
echo "    Ziel-Kompatibilität: glibc <= $MAX_GLIBC"

echo "==> Prüfe Dateien ..."
[[ -f "$MAIN_SCRIPT" ]] || { echo "FEHLER: $MAIN_SCRIPT nicht gefunden (Einstellung MAIN_SCRIPT)."; exit 1; }
[[ -f "$ICON" ]] || { echo "FEHLER: Icon $ICON nicht gefunden (Einstellung ICON)."; exit 1; }
command -v uv >/dev/null || { echo "FEHLER: uv nicht gefunden. Installieren: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

# ---------- 1. Python-Umgebung mit allen Modulen ----------
USES_TKINTER=""
grep -qsE '^\s*(import|from)\s.*\btkinter\b' ./*.py && USES_TKINTER="yes"
if [[ "$PYTHON_SOURCE" == "auto" ]]; then
    [[ -n "$USES_TKINTER" ]] && PYTHON_SOURCE="conda" || PYTHON_SOURCE="uv"
fi

BASE_PYTHON="$PYTHON_VERSION"
if [[ "$PYTHON_SOURCE" == "conda" ]]; then
    # Python + Tk (Xft-Variante) von conda-forge, einmalig nach build/ geladen.
    # Grund: Das Tk im uv-Python kann keine geglättete Schrift (kein Xft).
    MM_DIR="build/micromamba"
    MM="$MM_DIR/bin/micromamba"
    CONDA_PY="build/conda-python-$PYTHON_VERSION"
    if [[ ! -x "$MM" ]]; then
        echo "==> Lade micromamba (für Python mit schöner Tk-Schrift) ..."
        mkdir -p "$MM_DIR"
        curl -L --fail https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-linux-64.tar.bz2 \
            | tar xj -C "$MM_DIR" bin/micromamba
    fi
    if [[ ! -x "$CONDA_PY/bin/python" ]]; then
        echo "==> Lade Python $PYTHON_VERSION + Tk mit Xft von conda-forge ..."
        "$MM" create -y -q -r "$MM_DIR/root" -p "$CONDA_PY" -c conda-forge \
            "python=$PYTHON_VERSION" "tk=*=xft_*"
    fi
    BASE_PYTHON="$PROJECT_DIR/$CONDA_PY/bin/python"
fi

echo "==> Python-Umgebung (.venv) mit Python $PYTHON_VERSION ($PYTHON_SOURCE) ..."
# Jedes Mal frisch anlegen, damit keine alten Pakete (z. B. für neuere
# Systeme gebaute) übrig bleiben. Dank uv-Zwischenspeicher geht das schnell.
if [[ "$CLEAN_BUILD" == "yes" ]]; then
    rm -rf .venv
fi
if [[ ! -x ".venv/bin/python" ]]; then
    uv venv .venv --python "$BASE_PYTHON"
fi
PY_BASE="$(.venv/bin/python -c 'import sys; print(sys.base_prefix)')"

if [[ "$TARGET_PLATFORM" == "auto" ]]; then
    if [[ " $PACKAGES " == *" PySide6 "* ]] || grep -qsi '^pyside6' requirements.txt; then
        TARGET_PLATFORM="x86_64-manylinux_2_34"   # PySide6 gibt es nicht älter
        # PySide6 braucht mindestens glibc 2.34 -> Grenze anheben, sonst
        # würde die Prüfung am Ende jeden PySide6-Build abbrechen.
        if [[ "$(printf '%s\n' "$MAX_GLIBC" 2.34 | sort -V | head -n1)" != "2.34" ]]; then
            echo "    Hinweis: PySide6 braucht glibc 2.34 -> MAX_GLIBC von $MAX_GLIBC auf 2.34 angehoben."
            MAX_GLIBC="2.34"
        fi
    else
        TARGET_PLATFORM="x86_64-manylinux_2_17"
    fi
fi
PLATFORM_ARGS=()
if [[ -n "$TARGET_PLATFORM" ]]; then
    # --no-build: nie auf diesem Rechner kompilieren (das würde die glibc-
    # Grenze still hochsetzen), sondern automatisch die neueste Version
    # nehmen, die es fertig für die Zielplattform gibt.
    PLATFORM_ARGS=(--python-platform "$TARGET_PLATFORM" --no-build)
    echo "    Pakete in der Ausgabe für: $TARGET_PLATFORM"
fi

# Erlaubte Selbst-Kompilierungen zuerst installieren (ohne --no-build)
if [[ " $PACKAGES " == *" pynput "* ]] || grep -qsi '^pynput' requirements.txt; then
    BUILD_FROM_SOURCE="$BUILD_FROM_SOURCE evdev"
fi
if [[ -n "${BUILD_FROM_SOURCE// /}" ]]; then
    echo "    Wird hier kompiliert (erlaubt): $BUILD_FROM_SOURCE"
    # shellcheck disable=SC2086
    uv pip install --python .venv/bin/python $BUILD_FROM_SOURCE
fi

echo "    Installiere: $PACKAGES"
# shellcheck disable=SC2086
uv pip install --python .venv/bin/python "${PLATFORM_ARGS[@]}" $PACKAGES pyinstaller
if [[ -f requirements.txt ]]; then
    uv pip install --python .venv/bin/python "${PLATFORM_ARGS[@]}" -r requirements.txt
fi

# ---------- 2. Programm mit PyInstaller bauen ----------
echo "==> Baue Programm mit PyInstaller ..."
ADD_DATA=()
shopt -s nullglob nocaseglob
for pattern in $DATA_PATTERNS; do
    for f in $pattern; do
        ADD_DATA+=(--add-data "$PROJECT_DIR/$f:.")
    done
done
shopt -u nullglob nocaseglob
echo "    $(( ${#ADD_DATA[@]} / 2 )) Bild-/Datendatei(en) werden eingepackt."

# Unterordner mit Bildern/Tönen/Daten (z. B. "bild") komplett mitnehmen.
# Ausgenommen: Build-Ordner und Python-Pakete (Ordner mit __init__.py).
for dir in */; do
    dir="${dir%/}"
    case "$dir" in .venv|build|dist|__pycache__|.git) continue ;; esac
    [[ -f "$dir/__init__.py" ]] && continue
    found=""
    set -f   # Muster wie *.png NICHT von der Shell auflösen lassen
    for pattern in $DATA_PATTERNS; do
        if [[ -n "$(find "$dir" -type f -iname "$pattern" -print -quit 2>/dev/null)" ]]; then
            found=yes; break
        fi
    done
    set +f
    if [[ -n "$found" ]]; then
        ADD_DATA+=(--add-data "$PROJECT_DIR/$dir:$dir")
        echo "    Ordner \"$dir\" wird mit eingepackt ($(find "$dir" -type f | wc -l) Dateien)."
    fi
done

# Tkinter: Das portable Python von uv bringt Tcl/Tk als eigene Bibliotheken
# mit, die PyInstaller nicht von selbst findet -> ausdrücklich mitnehmen.
if [[ -n "$USES_TKINTER" ]]; then
    shopt -s nullglob
    for lib in "$PY_BASE"/lib/libtcl*.so* "$PY_BASE"/lib/libtk*.so*; do
        ADD_DATA+=(--add-binary "$lib:.")
    done
    shopt -u nullglob
    echo "    Tkinter erkannt: Tcl/Tk-Bibliotheken werden mit eingepackt."
fi

# Module mit nachgeladenen Teilen vollständig einpacken
# (pynput lädt z. B. pynput.keyboard._xorg erst beim Start -> sonst Absturz)
COLLECT_ARGS=()
AUTO_COLLECT=""
if [[ " $PACKAGES " == *" pynput "* ]] || grep -qsi '^pynput' requirements.txt; then
    AUTO_COLLECT="pynput Xlib evdev"
fi
for mod in $COLLECT $AUTO_COLLECT; do
    # Alle Untermodule aus den Dateien ablesen (nicht importieren: manche,
    # wie pynput.keyboard._xorg, brauchen beim Bauen sonst einen Bildschirm
    # und würden still übersprungen).
    while IFS= read -r sub; do
        [[ -n "$sub" ]] && COLLECT_ARGS+=(--hidden-import "$sub")
    done < <(.venv/bin/python - "$mod" <<'PYEOF'
import importlib.util, os, sys
spec = importlib.util.find_spec(sys.argv[1])
if spec and spec.submodule_search_locations:
    base = list(spec.submodule_search_locations)[0]
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, base)
        pkg = sys.argv[1] if rel == "." else sys.argv[1] + "." + rel.replace(os.sep, ".")
        for f in files:
            if f.endswith(".py"):
                print(pkg if f == "__init__.py" else pkg + "." + f[:-3])
PYEOF
)
done
[[ ${#COLLECT_ARGS[@]} -gt 0 ]] && echo "    Vollständig eingepackt: $COLLECT $AUTO_COLLECT ($(( ${#COLLECT_ARGS[@]} / 2 )) Module)"

rm -rf build/pyinstaller "dist/$APP_NAME"
.venv/bin/pyinstaller --noconfirm --clean --windowed \
    --name "$APP_NAME" \
    --icon "$ICON" \
    --workpath build/pyinstaller \
    --specpath build \
    --distpath dist \
    "${ADD_DATA[@]}" \
    "${COLLECT_ARGS[@]}" \
    "$PROJECT_DIR/$MAIN_SCRIPT"

# ---------- 2b. System-Bibliotheken des Build-Rechners entfernen ----------
if [[ "$STRIP_SYSTEM_LIBS" == "yes" ]]; then
    INTERNAL="dist/$APP_NAME/_internal"
    [[ -d "$INTERNAL" ]] || INTERNAL="dist/$APP_NAME"
    n=0
    shopt -s nullglob
    for lib in "$INTERNAL"/lib*.so*; do
        name="$(basename "$lib")"
        case "$name" in
            libQt6*|libpyside*|libshiboken*|libpython*) continue ;;   # Qt/Python: behalten
        esac
        # Bibliotheken, die vom mitgebrachten Python selbst stammen (z. B.
        # libffi, libssl bei conda-forge), sind portabel -> behalten.
        # Ausnahme: libgcc_s/libstdc++ hat jedes Linux; die conda-Versionen
        # würden die glibc-Grenze unnötig anheben.
        if [[ -e "$PY_BASE/lib/$name" && ! "$name" =~ ^lib(gcc_s|stdc\+\+) ]]; then
            continue
        fi
        if [[ "$name" =~ ^lib(X|xcb|xkbcommon|glib-|gio-|gobject-|gmodule-|gthread-|gtk-|gdk-|gdk_pixbuf|atk|atspi|cairo|pango|harfbuzz|fontconfig|freetype|expat|dbus-|GL|EGL|drm|gbm|wayland-|selinux|mount|blkid|cap\.|systemd|krb5|gssapi|k5crypto|com_err|keyutils|gcrypt|gpg-error|z\.|bz2|bsd|md\.|ffi|pcre|uuid|lz4|lzma|zstd|png|jpeg|tiff|graphite2|fribidi|datrie|thai|epoxy|pixman|brotli|gcc_s|stdc\+\+|crypto|ssl|sqlite|cups|avahi|gnutls|nettle|hogweed|gmp|idn|tasn1|p11|unistring|elf|tinfo|ncurses|readline|sharpyuv|webp|deflate|lerc|jbig|xml2|icu[a-z]*|asound|pulse|gst|orc-|sndfile|FLAC|ogg|vorbis|opus|mp3lame|mpg123|asyncns|apparmor|dw.|unwind|jack|portaudio|sox|soxr|speex|samplerate|wrap|nsl|resolv|dbus) ]]; then
            rm -f "$lib"; n=$((n + 1))
        fi
    done
    shopt -u nullglob
    echo "    $n System-Bibliothek(en) des Build-Rechners entfernt."
fi

# ---------- 3. AppDir zusammenstellen ----------
echo "==> Stelle AppImage-Ordner zusammen ..."
APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -a "dist/$APP_NAME" "$APPDIR/usr/bin/"

# Startskript: wechselt in den Ordner mit den Bildern, damit Code wie
# QPixmap("bild.png") die Bilder ohne Pfadangabe findet.
# Kennung für Startmenü-Eintrag und Symbol (gleich wie appimages_einbinden.sh)
APP_ID="appimage-$(printf '%s' "$APP_NAME" | tr -c 'A-Za-z0-9_-' '_')"

cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"

# --- Beim Start selbst ins System einbinden (Startmenü + Symbol) ---------
# Läuft nur, wenn noch kein Eintrag für GENAU diese Datei existiert, also beim
# ersten Start und nach dem Verschieben. Abschalten: AUTO_INTEGRATE="no" im
# Build-Skript oder beim Start APPIMAGE_NO_INTEGRATE=1 setzen.
if [ "$AUTO_INTEGRATE" = "yes" ] && [ -n "\$APPIMAGE" ] && [ "\${APPIMAGE_NO_INTEGRATE:-}" != "1" ]; then
    DATA="\${XDG_DATA_HOME:-\$HOME/.local/share}"
    DESK="\$DATA/applications/$APP_ID.desktop"
    ICON="\$DATA/icons/$APP_ID.png"
    if ! grep -qF "Exec=\"\$APPIMAGE\"" "\$DESK" 2>/dev/null; then
        mkdir -p "\$DATA/applications" "\$DATA/icons"
        cp -f "\$HERE/.DirIcon" "\$ICON" 2>/dev/null
        {
            echo "[Desktop Entry]"
            echo "Type=Application"
            echo "Name=$APP_NAME"
            echo "Exec=\"\$APPIMAGE\" %F"
            echo "Icon=\$ICON"
            echo "Categories=$CATEGORY"
            echo "Terminal=false"
        } > "\$DESK" 2>/dev/null
        chmod +x "\$DESK" 2>/dev/null
        update-desktop-database "\$DATA/applications" >/dev/null 2>&1
        # Symbol auch für die Datei im Dateimanager (Nemo/Nautilus)
        gio set "\$APPIMAGE" metadata::custom-icon "file://\$ICON" >/dev/null 2>&1
    fi
fi
# --------------------------------------------------------------------------

APPDATA="\$HERE/usr/bin/$APP_NAME/_internal"
[ -d "\$APPDATA" ] || APPDATA="\$HERE/usr/bin/$APP_NAME"
cd "\$APPDATA"
exec "\$HERE/usr/bin/$APP_NAME/$APP_NAME" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

cat > "$APPDIR/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Exec=$APP_NAME
Icon=$APP_NAME
Categories=$CATEGORY
Terminal=false
EOF

cp "$ICON" "$APPDIR/$APP_NAME.png"
cp "$ICON" "$APPDIR/.DirIcon"

# ---------- 4. appimagetool holen und AppImage bauen ----------
TOOL="build/appimagetool-x86_64.AppImage"
if [[ ! -x "$TOOL" ]]; then
    echo "==> Lade appimagetool herunter ..."
    curl -L --fail -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

echo "==> Baue AppImage ..."
OUT="dist/$APP_NAME-x86_64.AppImage"
rm -f "$OUT"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"

# Kontrolle: welche glibc-Version braucht das AppImage mindestens?
# (ohne objdump - liest die Versionsangaben direkt aus den Dateien)
.venv/bin/python - "$APPDIR" "$MAX_GLIBC" <<'PYEOF'
import os, re, sys
MAX_GLIBC = sys.argv[2]
pat = re.compile(rb"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?\x00")
best, best_file = (0,), ""
for root, _, files in os.walk(sys.argv[1]):
    for name in files:
        p = os.path.join(root, name)
        if os.path.islink(p):
            continue
        try:
            with open(p, "rb") as f:
                if f.read(4) != b"\x7fELF":
                    continue
                data = f.read()
        except OSError:
            continue
        for m in pat.finditer(data):
            v = tuple(int(x) for x in m.groups() if x)
            if v > best:
                best, best_file = v, os.path.relpath(p, sys.argv[1])
glibc_text = ".".join(map(str, best))
print(f"    Benötigt mindestens: glibc {glibc_text}  ({best_file})")

# Harte Kompatibilitätsprüfung gegen die gewünschte Zielgrenze.
max_parts = tuple(int(x) for x in MAX_GLIBC.split("."))
if best > max_parts:
    print()
    print(f"❌ FEHLER: Das AppImage benötigt glibc {glibc_text}.")
    print(f"   Ziel ist maximal glibc {MAX_GLIBC}.")
    sys.exit(1)

print(f"    ✅ glibc-Kompatibilität: <= {MAX_GLIBC}")
PYEOF

# ---------- 5. Abschlussprüfung ----------
echo "==> Prüfe fertiges AppImage ..."

[[ -f "$OUT" ]] || { echo "❌ AppImage fehlt."; exit 1; }
[[ -x "$OUT" ]] || { echo "❌ AppImage ist nicht ausführbar."; exit 1; }
[[ -x "$APPDIR/AppRun" ]] || { echo "❌ AppRun fehlt."; exit 1; }
[[ -f "$APPDIR/$APP_NAME.desktop" ]] || { echo "❌ Desktop-Datei fehlt."; exit 1; }
[[ -f "$APPDIR/$APP_NAME.png" ]] || { echo "❌ Icon fehlt."; exit 1; }

APP_SIZE="$(du -h "$OUT" | cut -f1)"

echo
echo "=============================================="
echo "   BUILD ERFOLGREICH"
echo "=============================================="
echo "   App:        $APP_NAME"
echo "   Architektur: x86_64"
echo "   glibc:       <= $MAX_GLIBC"
echo "   Größe:       $APP_SIZE"
echo "   Datei:       $PROJECT_DIR/$OUT"
echo
echo "   Starten mit:"
echo "   ./$OUT"
echo "=============================================="
