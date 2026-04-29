#!/usr/bin/env bash
# Orchestrate the v2 re-materialization: strip SFI, re-mint places,
# ensure every place has a label + type, then summarise.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &>/dev/null && pwd)"

V1_DIR="${V1_OUTPUT_DIR:-/mnt/d/Projets/voices/workspace/KG2026.paper/output}"
OUT_DIR="${REPO_ROOT}/output"
mkdir -p "${OUT_DIR}"

INPUT_NQ="${V1_DIR}/kg2026_paper.nq"
INPUT_EMB="${V1_DIR}/utterance_embeddings.nq"
INPUT_NQS="${V1_DIR}/kg2026_paper.nqs"

OUTPUT_NQ="${OUT_DIR}/kg2026_v2.nq"
OUTPUT_EMB="${OUT_DIR}/utterance_embeddings_v2.nq"
OUTPUT_NQS="${OUT_DIR}/kg2026_v2.nqs"
STATS="${OUT_DIR}/stats.json"

echo "==> Step 1/2: filter (strip SFI + drop concepts graph)"
FILTER_ARGS=(
  --input "${INPUT_NQ}"
  --output "${OUTPUT_NQ}"
  --stats "${STATS}"
)
if [[ -f "${INPUT_EMB}" ]]; then
  FILTER_ARGS+=(--embeddings "${INPUT_EMB}" --embeddings-out "${OUTPUT_EMB}")
fi
if [[ -f "${INPUT_NQS}" ]]; then
  FILTER_ARGS+=(--nqs-in "${INPUT_NQS}" --nqs-out "${OUTPUT_NQS}")
fi

(
  cd "${REPO_ROOT}"
  python3 -m src.rebuild.filter "${FILTER_ARGS[@]}"
)

echo "==> Step 2/2: relabel (ensure place labels + types in metadata graph)"
(
  cd "${REPO_ROOT}"
  python3 -m src.rebuild.relabel --input "${OUTPUT_NQ}"
)

echo "==> Stats summary"
if [[ -f "${STATS}" ]]; then
  cat "${STATS}"
fi

echo "==> Done. Outputs in ${OUT_DIR}"
