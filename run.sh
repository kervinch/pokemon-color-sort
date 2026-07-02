#!/usr/bin/env bash
# Build (if needed) and open the Pokémon Spectrum viewer.
set -euo pipefail
cd "$(dirname "$0")"

python3 -c "import PIL, numpy" 2>/dev/null || {
  echo "Installing Python dependencies (Pillow, numpy)..."
  python3 -m pip install --user Pillow numpy
}

if [ ! -f viewer/assets/mosaic.png ]; then
  echo "First run — building the mosaic (downloads ~2,700 sprites, packs, renders)."
  python3 -m pipeline.build
fi

PORT="${PORT:-8123}"
URL="http://localhost:${PORT}/viewer/"
echo "Serving at ${URL}"
( sleep 1; command -v open >/dev/null && open "$URL" ) &
exec python3 -m http.server "$PORT" --bind 127.0.0.1
