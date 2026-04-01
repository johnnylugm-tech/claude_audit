#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# audit.sh — methodology-v2 Phase Auditor 便利執行腳本
#
# 自動以 reports/OWNER/REPO/BRANCH/phaseN/YYYY-MM-DD_audit.md 命名儲存報告
#
# 使用方式：
#   ./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
#   ./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 2 --branch main
#   ./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 2 --branch phase2-claude-code-comparison
#   ./audit.sh --repo OWNER/REPO --phase 1 --output json
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO=""
PHASE=""
BRANCH="main"
OUTPUT="markdown"
EXTRA_ARGS=

# ── 參數解析 ─────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)    REPO="$2";    shift 2 ;;
        --phase)   PHASE="$2";   shift 2 ;;
        --branch)  BRANCH="$2";  shift 2 ;;
        --output)  OUTPUT="$2";  shift 2 ;;
        *)         EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [[ -z "$REPO" || -z "$PHASE" ]]; then
    echo "用法：$0 --repo OWNER/REPO --phase N [--branch BRANCH] [--output markdown|json]"
    exit 1
fi

# ── 路徑建立 ─────────────────────────────────────────────────────────────────
# reports/OWNER/REPO/BRANCH/phaseN/
OWNER=$(echo "$REPO" | cut -d'/' -f1)
REPO_NAME=$(echo "$REPO" | cut -d'/' -f2)
SAFE_BRANCH=$(echo "$BRANCH" | tr '/' '-')  # 分支名中的 / 轉成 -
DATE=$(date +%Y-%m-%d)
EXT="md"
[[ "$OUTPUT" == "json" ]] && EXT="json"

REPORT_DIR="reports/${OWNER}/${REPO_NAME}/${SAFE_BRANCH}/phase${PHASE}"
REPORT_FILE="${REPORT_DIR}/${DATE}_audit.${EXT}"

mkdir -p "$REPORT_DIR"

# ── 執行審計 ─────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Claude Audit — Phase ${PHASE} 審計                              "
echo "║  Repo  : ${REPO}                                             "
echo "║  Branch: ${BRANCH}                                          "
echo "║  Report: ${REPORT_FILE}                                     "
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

AUDITOR_ARGS=(--repo "$REPO" --phase "$PHASE" --branch "$BRANCH" --save "$REPORT_FILE")
[[ "${OUTPUT}" != "markdown" ]] && AUDITOR_ARGS+=(--output "$OUTPUT")

python3 "$(dirname "$0")/phase_auditor.py" "${AUDITOR_ARGS[@]}"

STATUS=$?

echo ""
echo "📁 報告路徑：$(pwd)/${REPORT_FILE}"

# 顯示裁決摘要
if [[ "$EXT" == "md" ]]; then
    echo ""
    echo "─── 裁決摘要 ───────────────────────────────────────────────────"
    grep -A4 "## 最終裁決" "$REPORT_FILE" | tail -n +3 | head -5 || true
    echo "────────────────────────────────────────────────────────────────"
fi

exit $STATUS
