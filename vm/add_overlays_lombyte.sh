#!/usr/bin/env bash
# Second provisioning step: level code (overlays) and Lombyte's progress report.
# Run as root on the VM after vm/provision.sh, WITH network, once.
#
#   scp -J JUMP "<your PAL disc image>.iso" VM:/opt/rac1/SCES_509.16.iso
#   bash vm/add_overlays_lombyte.sh
#
# Level functions (func_LNN_*) are not in SCES_509.16: each level's code is an
# overlay stored in the disc's level files. tools/overlays.py dump reads them
# from baserom/SCES_509.16.iso. Lombyte's matched-function list is published
# on its `progress` branch, which provision.sh did not fetch.
set -euo pipefail

REPLAY_DATE="${REPLAY_DATE:-2026-10-07T19:24:13Z}"
BASE=/opt/rac1
REPO=$BASE/rac1-decomp
LOMBYTE=/root/Projects/Lombyte
MANIFEST=$BASE/golden-manifest.txt
FUNCS="$(cd "$(dirname "$0")/.." && pwd)/functions/haiku55-2026-10-07.txt"

[ -f $BASE/SCES_509.16.iso ] || { echo "copy the disc image to $BASE/SCES_509.16.iso first"; exit 1; }
cd "$REPO"

echo "== disc image"
cp $BASE/SCES_509.16.iso baserom/SCES_509.16.iso
echo "iso_sha1 $(sha1sum baserom/SCES_509.16.iso | cut -d' ' -f1)" >> "$MANIFEST"

echo "== level overlays: dump, then disassemble"
bash tools/docker/run.sh python3 tools/overlays.py dump
bash tools/docker/run.sh bash tools/setup_asm.sh

echo "== Lombyte progress report as of the replay date"
tmp=$(mktemp -d)
git clone -q https://github.com/mateuszklysz/Lombyte "$tmp/l"
if git -C "$tmp/l" rev-parse -q --verify origin/progress >/dev/null; then
  c=$(git -C "$tmp/l" rev-list -1 --before="$REPLAY_DATE" origin/progress)
  if [ -n "$c" ]; then
    mkdir -p "$LOMBYTE/progress"
    git -C "$tmp/l" show "$c:report.json" > "$LOMBYTE/progress/report.json"
    echo "lombyte_progress $c" >> "$MANIFEST"
  fi
fi
rm -rf "$tmp"
[ -f "$LOMBYTE/progress/report.json" ] || echo "WARN: no Lombyte report before $REPLAY_DATE"
LOMBYTE=$LOMBYTE python3 tools/lombyte.py map || echo "WARN: lombyte map failed"

echo "== every pool function must have its assembly"
missing=0
while read -r f; do
  f="${f%%#*}"; f="$(echo "$f" | tr -d '[:space:]')"
  [ -z "$f" ] && continue
  if [ -f "asm/overlays/$f.s" ]; then echo "ok      $f"; else echo "MISSING $f"; missing=1; fi
done < "$FUNCS"

[ $missing = 0 ] && echo "OK: overlays ready" || { echo "FAIL: missing assembly above"; exit 1; }
