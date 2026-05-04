#!/usr/bin/env bash
# Deploys the transcript-stripped public .nq dump and the matching
# Downloads-page change to the production VM.
#
# Configure target via environment variables (defaults assume the SSH
# alias "voices-vm" exists in your ~/.ssh/config):
#
#   VOICES_VM_HOST=voices-vm   # ssh alias or user@host
#   VOICES_VM_REPO=/srv/voices-kg
#
# Prerequisites:
#   - VPN to the deployment network (if any) is up.
#   - SSH access works: `ssh "$VOICES_VM_HOST" hostname`
#   - output/kg2026_v2_public.nq has been generated locally:
#       python3 scripts/strip_transcript_text.py \
#           --input output/kg2026_v2.nq \
#           --output output/kg2026_v2_public.nq
#
# What it does:
#   1. SCPs the public .nq to $VOICES_VM_REPO/output/ on the VM (~2.6 GB).
#   2. SCPs the strip script (so the VM can regenerate the file later).
#   3. SCPs the updated app/pages/05_Downloads.py.
#   4. Restarts the Streamlit container so the new page is served.

set -euo pipefail

VM_HOST="${VOICES_VM_HOST:-voices-vm}"
VM_REPO="${VOICES_VM_REPO:-/srv/voices-kg}"
REPO_LOCAL="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Local repo:  $REPO_LOCAL"
echo "==> Remote host: $VM_HOST"
echo "==> Remote repo: $VM_REPO"

echo "==> [1/4] Sanity-check VM reachability"
ssh -o ConnectTimeout=5 "$VM_HOST" "echo VM reachable: \$(hostname); test -d $VM_REPO && echo repo found"

echo "==> [2/4] SCP public .nq dump to VM ($(du -h "$REPO_LOCAL/output/kg2026_v2_public.nq" | cut -f1))"
scp -p "$REPO_LOCAL/output/kg2026_v2_public.nq" "$VM_HOST:$VM_REPO/output/kg2026_v2_public.nq"

echo "==> [3/4] SCP strip script and updated Downloads page"
scp -p "$REPO_LOCAL/scripts/strip_transcript_text.py" "$VM_HOST:$VM_REPO/scripts/strip_transcript_text.py"
scp -p "$REPO_LOCAL/app/pages/05_Downloads.py"        "$VM_HOST:$VM_REPO/app/pages/05_Downloads.py"

echo "==> [4/4] Restart Streamlit container to pick up the new page"
ssh "$VM_HOST" "cd $VM_REPO && docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"

echo "==> Done. Verify by visiting the Downloads page on the live deployment."
