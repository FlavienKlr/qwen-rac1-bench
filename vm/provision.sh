#!/usr/bin/env bash
# Builds the "golden" state of the harness VM. Run as root on the VM, WITH
# network, once. Afterwards: cut the VM's outbound network in Proxmox and
# take the snapshot (README, step 3).
#
#   bash vm/provision.sh
#
# What it guarantees:
#   - the repository is the replay commit's tree with NO later history:
#     the agent cannot `git show` the commit that holds Haiku's answers;
#   - Lombyte, the toolchains, m2c and asm-differ are pinned to the replay
#     date, and their history is dropped too;
#   - the build image is built from the replay commit's own Dockerfile;
#   - the build matches retail before anything else happens.
set -euo pipefail

REPLAY_COMMIT="${REPLAY_COMMIT:-777a7b1315e025fad2522d3414d5b35200746e7e}"  # parent of the Haiku 5.5 trial commit
REPLAY_DATE="${REPLAY_DATE:-2026-10-07T19:24:13Z}"                          # that commit's date, UTC
BASE=/opt/rac1
REPO=$BASE/rac1-decomp
HARNESS_SRC="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST=$BASE/golden-manifest.txt

need() { command -v "$1" >/dev/null || { echo "missing $1"; exit 1; }; }

echo "== packages"
apt-get update -qq
apt-get install -y -qq git python3 python3-pip ripgrep jq docker.io ca-certificates tmux p7zip-full >/dev/null
# BuildKit for `docker build --platform` (Debian 12/13 package); the legacy builder is the fallback
apt-get install -y -qq docker-buildx >/dev/null 2>&1 || echo "docker-buildx not available, using the legacy builder"
systemctl enable --now docker
need git; need docker; need python3

mkdir -p $BASE && cd $BASE
[ -f $BASE/SCES_509.16 ] || { echo "From the PC first: scp -J JUMP SCES_509.16 VM:$BASE/"; exit 1; }

# Clone at full depth, export one commit's tree, keep no history.
snapshot_tree() {  # url, dest, commit-or-date
  local url=$1 dest=$2 at=$3 tmp commit
  tmp=$(mktemp -d)
  git clone -q "$url" "$tmp/src"
  if [[ "$at" =~ ^[0-9a-f]{40}$ ]]; then commit=$at
  else commit=$(git -C "$tmp/src" rev-list -1 --before="$at" HEAD)
  fi
  mkdir -p "$dest"
  git -C "$tmp/src" archive "$commit" | tar -x -C "$dest"
  rm -rf "$tmp"
  echo "$url $commit" >> "$MANIFEST"
}

: > "$MANIFEST"
echo "replay_commit $REPLAY_COMMIT" >> "$MANIFEST"
echo "replay_date $REPLAY_DATE" >> "$MANIFEST"

echo "== rac1-decomp at the replay commit, history dropped"
rm -rf "$REPO"
snapshot_tree https://github.com/OpenRAC/rac1-decomp.git "$REPO" "$REPLAY_COMMIT"
( cd "$REPO" && git init -q && git add -A && \
  git -c user.name=bench -c user.email=bench@localhost commit -qm "replay base $REPLAY_COMMIT" )

echo "== toolchains, m2c, asm-differ, Lombyte (pinned to the replay date)"
snapshot_tree https://github.com/AngheloAlf/SN-Systems-ProDG_for_PS2_3.01 "$REPO/toolchain/sn-prodg-3.01" "$REPLAY_DATE"
snapshot_tree https://github.com/AngheloAlf/sce_ps2_sdk_24 "$REPO/toolchain/sn-prodg-24" "$REPLAY_DATE"
snapshot_tree https://github.com/matt-kempster/m2c "$REPO/tools/ext/m2c" "$REPLAY_DATE"
snapshot_tree https://github.com/simonlindholm/asm-differ "$REPO/tools/ext/asm-differ" "$REPLAY_DATE"
mkdir -p /root/Projects
snapshot_tree https://github.com/mateuszklysz/Lombyte /root/Projects/Lombyte "$REPLAY_DATE"

echo "== the executable (copied beforehand to $BASE/SCES_509.16, outside the repo)"
mkdir -p "$REPO/baserom" && cp $BASE/SCES_509.16 "$REPO/baserom/SCES_509.16"
echo "79956931bd62fafd8d20fa2eae796dbaf2e15e83  $REPO/baserom/SCES_509.16" | sha1sum -c -

echo "== build image from the replay commit's Dockerfile (run.sh prefers a local image)"
cd "$REPO"
docker build --platform linux/386 -t rac1-build:latest -f tools/docker/Dockerfile .
echo "build_image $(docker image inspect rac1-build:latest --format '{{.Id}}')" >> "$MANIFEST"

echo "== host python deps (wave.py, dossier.py and lombyte.py run on the host, as upstream does)"
pip3 install -q --break-system-packages -r requirements.txt
echo "LOMBYTE=/root/Projects/Lombyte" >> /etc/environment

echo "== disassembly, Lombyte map, full build"
bash tools/docker/run.sh bash tools/setup_asm.sh
LOMBYTE=/root/Projects/Lombyte python3 tools/lombyte.py map || echo "WARN: lombyte map failed, note it"
bash tools/docker/run.sh bash tools/build_sn.sh 2>&1 | tee $BASE/golden-build.log

echo "== record the generated tree as the golden baseline (local repo only, never pushed)"
( cd "$REPO" && git add -A && git -c user.name=bench -c user.email=bench@localhost commit -qm "golden: generated files" || true )

echo "== harness"
rm -rf $BASE/harness && cp -r "$HARNESS_SRC/harness" $BASE/harness
cp -r "$HARNESS_SRC/functions" $BASE/functions
python3 -c "import json, urllib.request" && echo "harness: stdlib only, ok"

echo "== hashes of everything the agent must not change"
( cd "$REPO" && git ls-files -s | sha256sum ) | sed 's/^/tracked_tree /' >> "$MANIFEST"
cat "$MANIFEST"
echo
echo "Done. Check golden-build.log ends with a matching image, then run"
echo "vm/add_overlays_lombyte.sh (level code from the disc image, Lombyte's report), then:"
echo "  1. plan the wave (README step 4) BEFORE cutting the network if it needs docker pulls (it should not)"
echo "  2. cut outbound network in Proxmox, 3. snapshot 'golden'."
