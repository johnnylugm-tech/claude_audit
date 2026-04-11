# Quality Scorer — Content Quality Auditing Tool

獨立的內容品質評分系統，檢查 TH-01 ~ TH-17 品質指標。

## 功能

### Phase 1: 需求規格 (SRS.md)
- **TH-01**: ASPICE 合規性 (>80%) — 驗證功能/非功能/追蹤性章節
- **TH-14**: 規格完整性 (≥90%) — 統計 FR 定義與描述
- **TH-03**: 憲法正確性 (≥90%) — 檢查需求可測試性

### Phase 2: 架構設計 (SAD.md)
- **TH-01**: ASPICE 合規性 (>80%) — 驗證必要架構章節
- **TH-05**: 可維護性 (>70%) — ADR 狀態文件化
- **TH-03**: 憲法正確性 (≥80%) — 設計決策說明完整性

### Phase 3: 代碼實現
- **TH-06**: 代碼覆蓋率 (≥80%) — pytest --cov 測量
- **TH-10**: 測試通過率 (=100%) — pytest 執行結果
- **TH-11**: 單元測試覆蓋率 (≥70%) — 源代碼覆蓋率
- **TH-16**: 代碼↔SAD 映射 (≥80%) — @FR 註解檢測

## 使用方式

### CLI 執行
```bash
python3 quality_scorer.py --repo OWNER/REPO --phase 1 [--branch main]
```

### GitHub Actions Workflow
進入 "Actions" → "Quality Audit" → "Run workflow"

輸入：
- `repo`: 目標專案 (e.g., johnnylugm-tech/tts-kokoro-v613)
- `phase`: 審計階段 (1-8)
- `branch`: Git 分支 (預設 main)

### 輸出
- Markdown 報告：`reports/{owner}/{repo}/{branch}/quality_phase{n}.md`
- GitHub Artifact：自動保留 90 天

## 評分標準

| 評級 | 條件 |
|------|------|
| ✅ PASS | 所有檢查通過，0 個 CRITICAL |
| ⚠️ WARNING | 有警告但無嚴重問題 |
| ❌ FAIL | 有 CRITICAL 問題 |
| ℹ️ INFO | 不適用或可選檢查 |

## 文件結構

```
quality_scorer.py
├─ QualityScore: 評分結果容器
├─ QualityCheck: 單一檢查結果
├─ GitHubFetcher: GitHub API 存取
├─ QualityScorerPhase1: SRS 文件分析
├─ QualityScorerPhase2: SAD 文件分析
├─ QualityScorerPhase3: 代碼執行分析
└─ QualityScorer: 統一入口
```

## 開發

### 新增檢查
1. 在對應的 `QualityScorerPhaseN` 類中新增方法
2. 返回 `QualityCheck` 物件
3. 在 `check_all()` 中註冊

### 執行測試
```bash
python3 quality_scorer.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
python3 quality_scorer.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 2
python3 quality_scorer.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 3
```

## 依賴

- Python 3.10+
- `gh` CLI (GitHub 認證)
- `git` (repo cloning for Phase 3)
- `pytest`, `coverage` (Phase 3 可選)

## 相關文檔

- [methodology-v2](https://github.com/johnnylugm-tech/methodology-v2) — 審計框架
- [STAGE_PASS Template](https://github.com/johnnylugm-tech/methodology-v2#stage_pass) — 流程審計標準
