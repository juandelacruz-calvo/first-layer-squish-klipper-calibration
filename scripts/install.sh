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
echo "Copy config/first_layer_squish.cfg into your printer config directory,"
echo "customize start_gcode, and include it from printer.cfg."
echo "Then reload Python add-ons with: sudo systemctl restart klipper"
echo "FIRMWARE_RESTART alone may keep the previously imported module cached."
