#!/usr/bin/env bash
# =====================================================================
#  AppImage für "Ukrainische Silbentrennung Pro" (Uk_Silben) bauen
#
#  Aufruf im Projektordner (dort, wo Cargo.toml liegt):
#      bash build_appimage_rust.sh
#
#  Alle Einstellungen können auch von außen gesetzt werden (z. B. vom
#  AppImage Builder):  APP_NAME="X" bash build_appimage_rust.sh
#
#  Ergebnis:  dist/Uk_Silben-<Version>-x86_64.AppImage
#
#  Das Programm wird mit cargo-zigbuild für glibc 2.28 gebaut und läuft
#  damit ab Ubuntu 20.04, Linux Mint 20, Debian 10 und Fedora 29.
# =====================================================================
set -euo pipefail
# Projektordner: Ordner des Skripts, oder von außen vorgegeben (PROJECT_DIR)
cd "${PROJECT_DIR:-$(dirname "$(readlink -f "$0")")}"

# ---------------- Einstellungen ----------------
APP_ID="${APP_ID-de_syllable_hyphenator}"                         # muss zu APP_ID im Programm passen
APP_NAME="${APP_NAME-De_Silben}"
ICON_NAME="${ICON_NAME-Silben.png}"                     # dasselbe Icon wie im Programm (assets/Silben.png)
GLIBC="${GLIBC-2.28}"                               # älteste unterstützte glibc
TARGET="x86_64-unknown-linux-gnu"
COMMENT="${COMMENT-Ukrainian Syllable Hyphenator}"   # Beschreibung im Startmenü
CATEGORY="${CATEGORY-Office;Utility;}"              # Startmenü-Kategorie
# Fester Pfad zum Icon (sonst wird ICON_NAME in assets/ gesucht)
ICON="${ICON-}"
# Beim ersten Start selbst ins Startmenü eintragen (mit Symbol).
#   "yes" = automatisch   "no" = nie
AUTO_INTEGRATE="${AUTO_INTEGRATE:-yes}"

[ -f Cargo.toml ] || { echo "FEHLER: Cargo.toml nicht gefunden. Skript bitte in den Projektordner legen."; exit 1; }

# Werte aus Cargo.toml lesen:  section_value <Abschnitt> <Schlüssel>
section_value() {
    awk -v sec="$1" -v key="$2" '
        /^[[:space:]]*\[/ { insec = ($0 ~ "^[[:space:]]*" sec "[[:space:]]*$") ; next }
        insec && $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
            sub(/^[^=]*=[[:space:]]*"/, ""); sub(/".*$/, ""); print; exit }' Cargo.toml
}
# Programmname: aus [[bin]] (falls vorhanden), sonst aus [package]
# (lässt sich mit  BIN=MeinName bash build_appimage.sh  überschreiben)
BIN="${BIN:-$(section_value '\[\[bin\]\]' name)}"
BIN="${BIN:-$(section_value '\[package\]' name)}"
VERSION="$(section_value '\[package\]' version)"
VERSION="${VERSION:-1.0.0}"

# Icon suchen: neben der .rs-Datei aus [[bin]] path, sonst in assets/ oder src/assets/
BIN_PATH="$(section_value '\[\[bin\]\]' path)"
ICON_SRC=""
if [ -n "$ICON" ]; then
    [ -f "$ICON" ] && ICON_SRC="$ICON" || { echo "FEHLER: Icon $ICON nicht gefunden."; exit 1; }
fi
[ -n "$ICON_SRC" ] || for c in "$(dirname "${BIN_PATH:-src/main.rs}")/assets/$ICON_NAME" "assets/$ICON_NAME" "src/assets/$ICON_NAME"; do
    [ -f "$c" ] && { ICON_SRC="$c"; break; }
done
[ -n "$ICON_SRC" ] || { echo "FEHLER: $ICON_NAME weder in assets/ noch in src/assets/ gefunden."; exit 1; }
command -v wget >/dev/null || command -v curl >/dev/null || { echo "FEHLER: wget oder curl fehlt (sudo apt install wget)."; exit 1; }

echo "==> Programm: $BIN  Version: $VERSION  Icon: $ICON_SRC"

# ---------------- 1. Kompilieren ----------------
if command -v cargo-zigbuild >/dev/null; then
    echo "==> Baue mit cargo-zigbuild für glibc $GLIBC ..."
    cargo zigbuild --release --target "$TARGET.$GLIBC"
    EXE="target/$TARGET/release/$BIN"
else
    echo "WARNUNG: cargo-zigbuild fehlt – baue normal. Die AppImage läuft dann evtl."
    echo "         nicht auf älteren Linux-Systemen. Installieren mit:"
    echo "         cargo install cargo-zigbuild && pip install ziglang"
    cargo build --release
    EXE="target/release/$BIN"
fi
[ -x "$EXE" ] || { echo "FEHLER: $EXE nicht gefunden. Heißt die Programmdatei anders? Dann: BIN=Name bash $0"; exit 1; }
strip "$EXE" 2>/dev/null || true

# ---------------- 2. AppDir zusammenstellen ----------------
APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/512x512/apps"

cp "$EXE" "$APPDIR/usr/bin/$BIN"
cp "$ICON_SRC" "$APPDIR/$APP_ID.png"
cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
cp "$ICON_SRC" "$APPDIR/.DirIcon"

cat > "$APPDIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=$COMMENT
Exec=$BIN
Icon=$APP_ID
Terminal=false
Categories=$CATEGORY
StartupWMClass=$APP_ID
EOF
cp "$APPDIR/$APP_ID.desktop" "$APPDIR/usr/share/applications/"

# Kennung für den Startmenü-Eintrag (NICHT APP_ID – die gehört dem Fenster)
MENU_ID="appimage-$(printf '%s' "$APP_NAME" | tr -c 'A-Za-z0-9_-' '_')"

cat > "$APPDIR/AppRun" <<EOF
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\$0")")"

# --- Beim Start selbst ins System einbinden (Startmenü + Symbol) ---------
# Läuft nur, wenn noch kein Eintrag für GENAU diese Datei existiert, also beim
# ersten Start und nach dem Verschieben. Abschalten: AUTO_INTEGRATE="no" im
# Build-Skript oder beim Start APPIMAGE_NO_INTEGRATE=1 setzen.
if [ "$AUTO_INTEGRATE" = "yes" ] && [ -n "\$APPIMAGE" ] && [ "\${APPIMAGE_NO_INTEGRATE:-}" != "1" ]; then
    DATA="\${XDG_DATA_HOME:-\$HOME/.local/share}"
    DESK="\$DATA/applications/$MENU_ID.desktop"
    ICON="\$DATA/icons/$MENU_ID.png"
    if ! grep -qF "Exec=\"\$APPIMAGE\"" "\$DESK" 2>/dev/null; then
        mkdir -p "\$DATA/applications" "\$DATA/icons"
        cp -f "\$HERE/.DirIcon" "\$ICON" 2>/dev/null
        {
            echo "[Desktop Entry]"
            echo "Type=Application"
            echo "Name=$APP_NAME"
            echo "Comment=$COMMENT"
            echo "Exec=\"\$APPIMAGE\" %F"
            echo "Icon=\$ICON"
            echo "Categories=$CATEGORY"
            echo "StartupWMClass=$APP_ID"
            echo "Terminal=false"
        } > "\$DESK" 2>/dev/null
        chmod +x "\$DESK" 2>/dev/null
        update-desktop-database "\$DATA/applications" >/dev/null 2>&1
        # Symbol auch für die Datei im Dateimanager (Nemo/Nautilus)
        gio set "\$APPIMAGE" metadata::custom-icon "file://\$ICON" >/dev/null 2>&1
    fi
fi
# --------------------------------------------------------------------------

exec "\$HERE/usr/bin/$BIN" "\$@"
EOF
chmod +x "$APPDIR/AppRun"

# ---------------- 3. appimagetool holen ----------------
TOOL="tools/appimagetool-x86_64.AppImage"
if [ ! -x "$TOOL" ]; then
    echo "==> Lade appimagetool herunter ..."
    mkdir -p tools
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    if command -v wget >/dev/null; then wget -q --show-progress -O "$TOOL" "$URL"; else curl -L -o "$TOOL" "$URL"; fi
    chmod +x "$TOOL"
fi

# ---------------- 4. AppImage erzeugen ----------------
mkdir -p dist
OUT="dist/${BIN}-${VERSION}-x86_64.AppImage"
rm -f "$OUT"
# --appimage-extract-and-run: funktioniert auch ohne FUSE (z. B. Ubuntu 24.04 ohne libfuse2)
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"

echo
echo "Fertig: $OUT"
if command -v objdump >/dev/null; then
    echo "Benötigte glibc (höchste Version): $(objdump -T "$EXE" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)"
fi
