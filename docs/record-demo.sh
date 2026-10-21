#!/usr/bin/env bash
#
# Record the demo video for the Agent Governance & Monitoring POC.
#
#   ./docs/record-demo.sh            ->  docs/assets/demo.mp4  (+ demo.gif)
#
# Requires: vhs, ttyd and ffmpeg on PATH.
#   vhs   https://github.com/charmbracelet/vhs
#   ttyd  https://github.com/tsl0922/ttyd
#
# Each chapter lives in its own tape under docs/tapes/ so a single chapter can
# be re-recorded without redoing the whole video. The chapters are then
# concatenated in filename order.

set -euo pipefail

cd "$(dirname "$0")/.."

PART_DIR="docs/assets/parts"
OUT_MP4="docs/assets/demo.mp4"
OUT_GIF="docs/assets/demo.gif"

for tool in vhs ttyd ffmpeg; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "error: '$tool' is not on PATH" >&2
    exit 1
  }
done

if [ ! -d ".venv" ]; then
  echo "error: .venv not found - run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

# The tapes call "python", so make sure the virtualenv is the one they find.
# shellcheck disable=SC1091
source .venv/bin/activate

rm -rf "$PART_DIR"
mkdir -p "$PART_DIR"

for tape in docs/tapes/*.tape; do
  echo "==> recording $(basename "$tape")"
  vhs "$tape"
done

echo "==> concatenating chapters"
LIST="$(mktemp)"
for part in "$PART_DIR"/*.mp4; do
  printf "file '%s'\n" "$(realpath "$part")" >> "$LIST"
done
ffmpeg -y -loglevel error -f concat -safe 0 -i "$LIST" -c copy "$OUT_MP4"
rm -f "$LIST"

echo "==> rendering the GIF (for the README)"
ffmpeg -y -loglevel error -i "$OUT_MP4" \
  -vf "fps=12,scale=1000:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192[p];[b][p]paletteuse=dither=bayer:bayer_scale=3" \
  "$OUT_GIF"

rm -rf "$PART_DIR"

echo
echo "done:"
ls -lh "$OUT_MP4" "$OUT_GIF"
