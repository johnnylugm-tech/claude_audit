# Claude Audit — methodology-v2 Phase Auditor

> 基於 methodology-v2 v6.13 SKILL.md 規範，對 AI Agent 宣稱完成的 Phase 產物進行**獨立、自動化**稽核。

---

## 核心理念

稽核者**只能存取 GitHub 上的產物**（不執行本地程式碼）。程式透過 `gh` CLI 存取目標 repo 的：

- 檔案樹（確認交付物存在）
- 文件內容（驗證結構與深度）
- Commit 歷史（分析時間線合理性）

並從 8 個維度給出有依據的審計裁決。

---

## 8 個審計維度

| Check | 維度 | 對應規則 |
|-------|------|---------|
| C1 | 交付物完整性 | HR-08 |
| C2 | STAGE_PASS 憑證結構 | HR-08、HR-11 |
| C3 | A/B Session 分離驗證 | HR-01、HR-10 |
| C4 | DEVELOPMENT_LOG 品質（QG 實際輸出） | HR-02、HR-07 |
| C5 | Phase 核心文件內容深度 | HR-08 |
| C6 | Commit 時間線合理性 | HR-03 |
| C7 | Claims 交叉驗證（STAGE_PASS vs LOG） | HR-09 |
| C8 | Integrity Tracker 狀態 | HR-09 |

---

## 安裝

```bash
# 1. 確認 gh CLI 已安裝並登入
gh auth status

# 2. clone 此 repo
git clone https://github.com/johnnylugm-tech/claude_audit.git
cd claude_audit

# 3. 安裝 Python 依賴（僅標準庫，無需額外安裝）
python3 --version  # 需要 3.9+
```

---

## 使用方式

### 方法一：便利腳本（推薦）

```bash
# 稽核某專案的某 Phase（報告自動儲存到對應資料夾）
./audit.sh --repo OWNER/REPO --phase N

# 範例
./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 2
./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 2 --branch phase2-claude-code-comparison

# 輸出 JSON 格式
./audit.sh --repo johnnylugm-tech/tts-kokoro-v613 --phase 1 --output json
```

報告自動儲存至：
```
reports/
└── OWNER/
    └── REPO/
        └── BRANCH/
            └── phaseN/
                └── YYYY-MM-DD_audit.md
```

### 方法二：直接執行 Python

```bash
python3 phase_auditor.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
python3 phase_auditor.py --repo OWNER/REPO --phase 2 --branch dev --save my_report.md
```

---

## 報告結構

```
reports/
└── johnnylugm-tech/
    └── tts-kokoro-v613/
        ├── main/
        │   ├── phase1/
        │   │   └── 2026-04-01_audit.md    ← 原始執行團隊 Phase 1
        │   └── phase2/
        │       └── 2026-04-01_audit.md    ← 原始執行團隊 Phase 2
        └── phase2-claude-code-comparison/
            └── phase2/
                └── 2026-04-01_audit.md    ← Claude Code 對照組 Phase 2
```

---

## 裁決標準

| 裁決 | 條件 |
|------|------|
| ✅ PASS | CRITICAL = 0 且分數 ≥ 60 |
| ⚠️ CONDITIONAL_PASS | CRITICAL ≤ 1 且分數 ≥ 40 |
| ❌ FAIL | CRITICAL ≥ 2 或分數 < 40 |

分數公式：`(PASS×1 − WARNING×0.3 − CRITICAL×1.5) / total × 100`

---

## 新增稽核的 SOP

1. 執行 `./audit.sh --repo OWNER/REPO --phase N [--branch BRANCH]`
2. 報告自動儲存到 `reports/OWNER/REPO/BRANCH/phaseN/YYYY-MM-DD_audit.md`
3. `git add reports/ && git commit -m "audit: OWNER/REPO phase N — VERDICT"`
4. `git push`

---

## 已稽核專案

| 專案 | 分支 | Phase | 裁決 | 稽核日期 |
|------|------|-------|------|---------|
| johnnylugm-tech/tts-kokoro-v613 | main | 1 | ✅ PASS | 2026-04-01 |
| johnnylugm-tech/tts-kokoro-v613 | main | 2 | ✅ PASS | 2026-04-01 |
| johnnylugm-tech/tts-kokoro-v613 | phase2-claude-code-comparison | 2 | ✅ PASS (71.1) | 2026-04-01 |

---

## 方法論參考

- **SKILL.md**：[johnnylugm-tech/methodology-v2](https://github.com/johnnylugm-tech/methodology-v2)
- **版本**：methodology-v2 v6.13
- **8 Phase SDLC**：需求規格 → 架構設計 → 代碼實現 → 測試 → 驗證交付 → 品質保證 → 風險管理 → 配置管理
