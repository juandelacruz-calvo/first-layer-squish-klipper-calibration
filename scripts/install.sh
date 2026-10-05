#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
KLIPPER_DIR="${KLIPPER_DIR:-${HOME}/klipper}"
EXTRAS_DIR="${KLIPPER_DIR}/klippy/extras"
SOURCE_FILE="${PROJECT_DIR}/klippy/extras/first_layer_squish.py"
TARGET_FILE="${EXTRAS_DIR}/first_layer_squish.py"

if [[ ! -d "${EXTRAS_DIR}" ]]; then
    echo "Klipper extras directory not found: ${EXTRAS_DIR}" >&2
    echo "Set KLIPPER_DIR to the correct Klipper checkout and try again." >&2
    exit 1
fi

ln -sfn "${SOURCE_FILE}" "${TARGET_FILE}"
echo "Installed first_layer_squish.py at ${TARGET_FILE}"

# Keep the add-on visible to Klipper without marking Klipper's Git checkout
# dirty or triggering Moonraker's untracked-source warning. This exclude is local to the
# Klipper checkout and does not modify its tracked files.
if git -C "${KLIPPER_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    EXCLUDE_FILE="$(git -C "${KLIPPER_DIR}" rev-parse --path-format=absolute --git-path info/exclude)"
    if ! grep -Fxq 'klippy/extras/first_layer_squish.py' "${EXCLUDE_FILE}"; then
        printf '\n%s\n' 'klippy/extras/first_layer_squish.py' >> "${EXCLUDE_FILE}"
    fi
    echo "Excluded the symlink from Klipper's local Git status: ${EXCLUDE_FILE}"
fi

echo "Copy config/first_layer_squish.cfg into your printer config directory,"
echo "customize start_gcode, and include it from printer.cfg."
echo "Then reload Python add-ons with: sudo systemctl restart klipper"
echo "FIRMWARE_RESTART alone may keep the previously imported module cached."
