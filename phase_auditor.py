#!/usr/bin/env python3
"""
phase_auditor.py — methodology-v2 v8.0 Phase Audit Engine
============================================================
審計者視角：只能存取 GitHub 某個階段的所有產出物，
對 AI Agent 宣稱通過的 Phase 進行獨立驗證，輸出最終審計報告。

使用方式：
    python phase_auditor.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
    python phase_auditor.py --repo OWNER/REPO --phase 2 --methodology-version v7.5

初始化必要資訊（project_context）：
    --repo          GitHub repo (owner/repo)           [必填]
    --phase         審計階段編號 1-8                    [必填]
    --branch        目標分支 (預設: main)               [選填]
    --project-name  專案顯示名稱                        [選填，自動從 repo 推斷]
    --methodology-version  v8.0 (預設)                [選填]
"""

import argparse
import base64
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

# Configure logging for diagnostics
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# ─────────────────────────────────────────────
# 1. METHODOLOGY-V2 v8.0 規則庫（硬編碼，不依賴遠端框架）
# ─────────────────────────────────────────────

HARD_RULES = {
    "HR-01": "A/B 必須不同 Agent，禁止自寫自審",
    "HR-02": "Quality Gate 必須有實際命令輸出",
    "HR-03": "Phase 必須順序執行，不可跳過",
    "HR-07": "DEVELOPMENT_LOG 必須記錄 session_id",
    "HR-08": "每個 Phase 結束必須執行 Quality Gate",
    "HR-09": "Claims Verifier 驗證必須通過",
    "HR-10": "sessions_spawn.log 必須存在且有 A/B 記錄",
    "HR-11": "Phase Truth 分數 < 70% 禁止進入下一 Phase",
    # v6.15 新增: 煞車系統
    "HR-12": "A/B 審查同一 Phase 超過 5 輪 → 強制 PAUSE，等待人工裁決",
    "HR-13": "Phase 執行時長超過預估時間的 3 倍 → 強制 checkpoint，PAUSE 等待裁決",
    "HR-14": "Integrity 分數降至 < 40 → FREEZE 專案，全面審計後才能繼續",
    # v7.5 新增
    "HR-15": "citations 格式：檔案#L行號 或 檔案#L起始-L結束 + artifact_verification，缺少則 Integrity -15",
}

# v6.21 新增: 負面約束違規扣分（Integrity Tracker 補充項）
NEGATIVE_CONSTRAINTS = {
    "unable_to_proceed_no_reason": ("回傳 unable_to_proceed 但未說明原因", -15),
    "fabricated_content": ("嘗試編造無法完成的內容", -20),
    "ellipsis_in_code": ("程式碼中使用省略號 ... 代替實際實作", -10),
    "missing_summary": ("Agent 回傳缺少 50 字內摘要（Phase 3+）", -10),
    "missing_confidence": ("Agent 回傳缺少 confidence 1-10 自評分", -5),
    # v7.5 新增
    "subagent_inheriting_context": ("Subagent 繼承父級上下文", -15),
}

# 每個 Phase 的規格（依 SKILL.md v8.0 Phase 路由表）
PHASE_SPEC = {
    1: {
        "name": "需求規格",
        "agent_a": "architect",
        "agent_b": "reviewer",
        "ab_rounds": 1,
        "constitution_type": "srs",
        # 必要交付物：(路徑候選列表, 說明, 是否強制)
        "deliverables": [
            (["01-requirements/SRS.md", "SRS.md", "docs/SRS.md"],
             "SRS.md — 軟體需求規格", True),
            (["01-requirements/SPEC_TRACKING.md", "SPEC_TRACKING.md", "docs/SPEC_TRACKING.md"],
             "SPEC_TRACKING.md — 規格追蹤表", True),
            (["01-requirements/TRACEABILITY_MATRIX.md", "TRACEABILITY_MATRIX.md", "docs/TRACEABILITY_MATRIX.md"],
             "TRACEABILITY_MATRIX.md — 追溯矩陣", True),
            (["DEVELOPMENT_LOG.md"],
             "DEVELOPMENT_LOG.md — 開發日誌", True),
            (["sessions_spawn.log"],
             "sessions_spawn.log — A/B session 記錄", True),
            (["00-summary/Phase1_STAGE_PASS.md",
              "00-summary/Phase_1_-_需求規格_STAGE_PASS.md",
              "Phase1_STAGE_PASS.md"],
             "Phase1_STAGE_PASS.md — 階段通過憑證", True),
        ],
        "thresholds": {
            "TH-01": ("ASPICE 合規率", ">80%"),
            "TH-03": ("Constitution 正確性", "=100%"),
            "TH-04": ("Security 合規", "≥80%"),  # v8.0 新增
            "TH-14": ("規格完整性", "≥90%"),
        },
        # SRS 最低 FR 數
        "min_fr_count": 3,
        # SRS 必須包含的 section 關鍵字
        "srs_required_sections": ["功能需求", "FR-", "邏輯驗證方法"],
        # SPEC_TRACKING 必要欄位
        "spec_tracking_required_cols": ["FR", "描述", "狀態"],
        # TRACEABILITY 必要欄位（Phase 1 初始化即可，模組欄位可為「待實作」）
        "traceability_required_cols": ["FR", "模組"],
        # 最短合理執行時間（分鐘）
        "min_duration_minutes": 5,
    },
    2: {
        "name": "架構設計",
        "agent_a": "architect",
        "agent_b": "reviewer",
        "ab_rounds": 1,
        "constitution_type": "sad",
        "deliverables": [
            (["02-architecture/SAD.md", "SAD.md", "docs/SAD.md"],
             "SAD.md — 架構設計文件", True),
            (["02-architecture/ADR.md", "adr/adr.py", "docs/ADR_GUIDE.md",
              "02-architecture/adr/", "02-architecture/adr.md"],
             "ADR — 架構決策記錄", False),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase_2_-_架構設計_STAGE_PASS.md", "00-summary/Phase2_STAGE_PASS.md"],
             "Phase_2_-_架構設計_STAGE_PASS.md", True),
        ],
        "thresholds": {
            "TH-01": ("ASPICE 合規率", ">80%"),
            "TH-03": ("Constitution 正確性", "=100%"),
            "TH-04": ("Security 合規", "≥80%"),  # v8.0 新增
            "TH-05": ("Constitution 可維護性", ">70%"),
        },
        "min_duration_minutes": 10,
    },
    3: {
        "name": "代碼實現",
        "agent_a": "developer",
        "agent_b": "reviewer",
        "ab_rounds": -1,  # 每模組一次
        "constitution_type": "implementation",
        "deliverables": [
            (["03-development/src", "src", "03-implementation/src"],
             "src/ — 源代碼目錄", True),
            (["tests/", "03-development/tests/"],
             "tests/ — 單元測試", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase3_STAGE_PASS.md", "Phase3_STAGE_PASS.md",
          "00-summary/Phase_3_-_實作_STAGE_PASS.md", "Phase_3_-_實作_STAGE_PASS.md"],
             "Phase3_STAGE_PASS.md（或中文版）", True),
        ],
        "thresholds": {
            "TH-04": ("Security 合規", "≥80%"),  # v8.0 新增
            "TH-10": ("測試通過率", "=100%"),
            "TH-11": ("單元測試覆蓋率", "≥70%"),
            "TH-16": ("代碼 ↔ SAD 映射率", "=100%"),  # v6.15 新增
        },
        "min_duration_minutes": 30,
        "check_fr_annotations": True,    # v6.15: @FR annotation 檢查
    },
    4: {
        "name": "測試",
        "agent_a": "qa",
        "agent_b": "reviewer",
        "ab_rounds": 2,
        "constitution_type": "test_plan",
        "deliverables": [
            (["04-testing/TEST_PLAN.md", "TEST_PLAN.md"],
             "TEST_PLAN.md", True),
            (["04-testing/TEST_RESULTS.md", "TEST_RESULTS.md"],
             "TEST_RESULTS.md", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase4_STAGE_PASS.md", "Phase4_STAGE_PASS.md"],
             "Phase4_STAGE_PASS.md", True),
        ],
        "thresholds": {
            "TH-04": ("Security 合規", "≥80%"),  # v8.0 新增
            "TH-05": ("Constitution 可維護性", ">70%"),  # v8.0 新增
            "TH-10": ("測試通過率", "=100%"),
            "TH-12": ("單元測試覆蓋率", "≥80%"),
            "TH-17": ("FR ↔ 測試映射率", "≥90%"),  # v6.15 新增
        },
        "min_duration_minutes": 10,
        "check_covers_annotations": True,  # v6.15: @covers annotation 檢查
    },
    5: {
        "name": "驗證交付",
        "agent_a": "devops",
        "agent_b": "architect",
        "ab_rounds": 2,
        "constitution_type": "verification",  # v8.0: was None
        "deliverables": [
            (["05-verify/BASELINE.md", "BASELINE.md"],
             "BASELINE.md（7章節）", True),
            (["05-verify/VERIFICATION_REPORT.md", "VERIFICATION_REPORT.md"],
             "VERIFICATION_REPORT.md", True),
            (["05-verify/MONITORING_PLAN.md", "MONITORING_PLAN.md"],
             "MONITORING_PLAN.md", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase5_STAGE_PASS.md", "Phase5_STAGE_PASS.md"],
             "Phase5_STAGE_PASS.md", True),
        ],
        "thresholds": {
            "TH-02": ("Constitution 總分", "≥80%"),
            "TH-07": ("邏輯正確性分數", "≥90分"),
        },
        "min_duration_minutes": 15,
    },
    6: {
        "name": "品質保證",
        "agent_a": "qa",
        "agent_b": "architect",
        "ab_rounds": 1,
        "constitution_type": "srs",  # v8.0: re-checks SRS/SAD/Impl
        "deliverables": [
            (["06-quality/QUALITY_REPORT.md", "QUALITY_REPORT.md"],
             "QUALITY_REPORT.md（7章節）", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase6_STAGE_PASS.md", "Phase6_STAGE_PASS.md"],
             "Phase6_STAGE_PASS.md", True),
        ],
        "thresholds": {
            "TH-02": ("Constitution 總分", "≥80%"),
            "TH-07": ("邏輯正確性分數", "≥90分"),
        },
        "min_duration_minutes": 10,
    },
    7: {
        "name": "風險管理",
        "agent_a": "qa",
        "agent_b": "architect",
        "ab_rounds": 1,
        "constitution_type": "risk_management",  # v8.0: was None
        "deliverables": [
            (["07-risk/RISK_ASSESSMENT.md", "RISK_ASSESSMENT.md"],
             "RISK_ASSESSMENT.md", True),
            (["07-risk/RISK_REGISTER.md", "RISK_REGISTER.md"],
             "RISK_REGISTER.md", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase7_STAGE_PASS.md", "Phase7_STAGE_PASS.md"],
             "Phase7_STAGE_PASS.md", True),
        ],
        "thresholds": {
            "TH-07": ("邏輯正確性分數", "≥90分"),
        },
        "min_duration_minutes": 10,
    },
    8: {
        "name": "配置管理",
        "agent_a": "devops",
        "agent_b": "architect",
        "ab_rounds": 1,
        "constitution_type": "configuration",  # v8.0: was None
        "deliverables": [
            (["08-config/CONFIG_RECORDS.md", "CONFIG_RECORDS.md"],
             "CONFIG_RECORDS.md（8章節）", True),
            (["DEVELOPMENT_LOG.md"], "DEVELOPMENT_LOG.md", True),
            (["sessions_spawn.log"], "sessions_spawn.log", True),
            (["00-summary/Phase8_STAGE_PASS.md", "Phase8_STAGE_PASS.md"],
             "Phase8_STAGE_PASS.md", True),
        ],
        "thresholds": {},
        "min_duration_minutes": 10,
    },
}

# DEVELOPMENT_LOG 品質關鍵字：合格的 QG 輸出必須包含這些模式之一
QG_EVIDENCE_PATTERNS = [
    r"Constitution.*?[\d.]+%",
    r"Compliance Rate.*?[\d.]+%",
    r"ASPICE.*?(?:PASS|FAIL|✅|❌)",
    r"pytest.*?(?:passed|failed|error)",
    r"coverage.*?[\d]+%",
    r"stage.pass.*?(?:\d+)/100",
    r"phase.verify.*?(?:PASS|FAIL|[\d]+%)",
    r"enforce.*?(?:BLOCK|PASS|0.*?違規)",
    r"Constitution Score.*?[\d.]+",
    r"(?:Verify_Agent|verify_agent|Verifier|第三方驗證).*?(?:PASS|FAIL|完成|執行)",  # v6.21
    # v7.5 新增: HR-15 Layer 3 工具
    r"verify_citations\.py.*?(?:PASS|FAIL|\d+\s*files|\d+\s*Citations)",
    r"citation_enforcer\.py.*?(?:PASS|FAIL|passed|invalid)",
]

# DEVELOPMENT_LOG 假通過偵測（禁止只出現這些空泛標記）
FAKE_PASS_PATTERNS = [
    r"^[✅✓]\s*(?:已通過|通過|PASS|完成)\s*$",
    r"^[✅✓]\s*Phase\s*\d+\s*(?:完成|PASS|通過)\s*$",
]

# STAGE_PASS 必要章節（v7.12: 7 H2 sections，對齊 stage_pass_generator.py）
STAGE_PASS_REQUIRED_SECTIONS = [
    "階段目標達成",
    "Agent A 自評",
    "Agent B 審查",
    "Phase Challenges",
    "artifact_verification",
    "SIGN-OFF",
]

# STAGE_PASS H3 子章節（v7.12: 關鍵 H3，缺少則 WARNING）
STAGE_PASS_SUBSECTIONS = [
    "Phase Completion Summary",
    "交付物清單",
    "Agent A Confidence Summary",
    "Agent B Confidence Summary",
    "Phase Summary",
]

# v6.21 新增: STAGE_PASS 結構化欄位（Agent 回傳格式規範）
STAGE_PASS_STRUCTURED_FIELDS = [
    "confidence",   # 1-10 自評分
    "summary",      # 50字內摘要
]

# STAGE_PASS Agent B 必要關鍵字
STAGE_PASS_AGENT_B_KEYWORDS = [
    "APPROVE", "reviewer", "裁決", "審查", "✅ APPROVE"
]


# ─────────────────────────────────────────────
# 2. 資料結構
# ─────────────────────────────────────────────

@dataclass
class Finding:
    """單一審計發現"""
    check_id: str          # e.g. "C1-01"
    dimension: str         # e.g. "交付物完整性"
    severity: str          # CRITICAL / WARNING / INFO / PASS
    title: str
    detail: str
    evidence: str = ""     # 從檔案中截取的證據片段
    rule_ref: str = ""     # 對應的 HR-XX 或 TH-XX


@dataclass
class AuditResult:
    """完整審計結果"""
    repo: str
    phase: int
    phase_name: str
    audit_time: str
    findings: list[Finding] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "PENDING"  # PASS / CONDITIONAL_PASS / FAIL

    def add(self, finding: Finding):
        self.findings.append(finding)

    def criticals(self):
        return [f for f in self.findings if f.severity == "CRITICAL"]

    def warnings(self):
        return [f for f in self.findings if f.severity == "WARNING"]

    def passes(self):
        return [f for f in self.findings if f.severity == "PASS"]


# ─────────────────────────────────────────────
# 3. GITHUB API 存取層
# ─────────────────────────────────────────────

class GitHubFetcher:
    """透過 gh CLI 存取 GitHub Repo（不依賴 token 環境變數）"""

    def __init__(self, repo: str, branch: str = "main"):
        self.repo = repo
        self.branch = branch
        self._tree: Optional[list[dict]] = None
        self._file_cache: dict[str, Optional[str]] = {}

    def _gh(self, endpoint: str) -> Any:
        """執行 gh api 命令"""
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[gh api] {endpoint} failed: {result.stderr.strip()}", file=sys.stderr)
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def get_tree(self) -> list[dict]:
        """取得整個 repo 的檔案樹（含目錄和檔案）"""
        if self._tree is not None:
            return self._tree
        data = self._gh(
            f"repos/{self.repo}/git/trees/{self.branch}?recursive=1"
        )
        if not data or "tree" not in data:
            self._tree = []
        else:
            self._tree = data["tree"]
        return self._tree

    def get_files(self) -> list[dict]:
        """取得整個 repo 的檔案樹（僅檔案，不含目錄）"""
        return [item for item in self.get_tree() if item.get("type") == "blob"]

    def file_exists(self, path: str) -> bool:
        """檢查檔案或目錄是否存在（支援尾部 / 移除）"""
        normalized = path.rstrip("/")
        tree = self.get_tree()
        return any(item["path"] == normalized for item in tree)

    def resolve_path(self, candidates: list[str]) -> Optional[str]:
        """從候選路徑列表中找到第一個存在的路徑"""
        for path in candidates:
            if self.file_exists(path):
                return path
        return None

    def get_file_content(self, path: str) -> Optional[str]:
        """取得檔案內容（UTF-8 文字）"""
        if path in self._file_cache:
            return self._file_cache[path]
        data = self._gh(
            f"repos/{self.repo}/contents/{quote(path, safe='/')}?ref={self.branch}"
        )
        if not data or "content" not in data:
            self._file_cache[path] = None
            return None
        try:
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            self._file_cache[path] = content
            return content
        except (base64.binascii.Error, UnicodeDecodeError, KeyError) as e:
            logging.warning(f"Failed to decode {path}: {e}")
            self._file_cache[path] = None
            return None

    def get_commits(self, per_page: int = 30) -> list[dict]:
        """取得最新 commits"""
        data = self._gh(
            f"repos/{self.repo}/commits?per_page={per_page}&sha={self.branch}"
        )
        return data if isinstance(data, list) else []

    def get_repo_info(self) -> dict:
        data = self._gh(f"repos/{self.repo}")
        return data or {}


# ─────────────────────────────────────────────
# 4. 審計檢查器（各維度）
# ─────────────────────────────────────────────

class PhaseAuditor:
    def __init__(self, fetcher: GitHubFetcher, phase: int):
        self.gh = fetcher
        self.phase = phase
        if phase not in PHASE_SPEC:
            raise ValueError(f"Unsupported phase: {phase}. Supported: 1-8")
        self.spec = PHASE_SPEC[phase]
        self.result = AuditResult(
            repo=fetcher.repo,
            phase=phase,
            phase_name=self.spec.get("name", f"Phase {phase}"),
            audit_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )
        # 解析到的實際路徑快取
        self._resolved: dict[str, Optional[str]] = {}

    def _resolve(self, candidates: list[str]) -> Optional[str]:
        key = candidates[0]
        if key not in self._resolved:
            self._resolved[key] = self.gh.resolve_path(candidates)
        return self._resolved[key]

    def _content(self, candidates: list[str]) -> Optional[str]:
        path = self._resolve(candidates)
        if not path:
            return None
        return self.gh.get_file_content(path)

    # ── C1: 交付物完整性 ──────────────────────────────
    def check_c1_deliverables(self):
        """C1: 必要交付物存在性檢查"""
        spec = self.spec
        for candidates, description, required in spec.get("deliverables", []):
            path = self._resolve(candidates)
            if path:
                self.result.add(Finding(
                    check_id="C1",
                    dimension="交付物完整性",
                    severity="PASS",
                    title=f"✅ {description}",
                    detail=f"找到：{path}",
                ))
            elif required:
                self.result.add(Finding(
                    check_id="C1",
                    dimension="交付物完整性",
                    severity="CRITICAL",
                    title=f"❌ 缺少必要交付物：{description}",
                    detail=f"搜尋路徑：{', '.join(candidates)}",
                    rule_ref="HR-08",
                ))
            else:
                self.result.add(Finding(
                    check_id="C1",
                    dimension="交付物完整性",
                    severity="WARNING",
                    title=f"⚠️ 缺少建議交付物：{description}",
                    detail=f"搜尋路徑：{', '.join(candidates)}",
                ))

    # ── C2: STAGE_PASS 結構分析 ───────────────────────
    def check_c2_stage_pass(self):
        """C2: STAGE_PASS 憑證完整性與品質"""
        candidates = [
            f"00-summary/Phase{self.phase}_STAGE_PASS.md",
            f"00-summary/Phase_{self.phase}_-_*_STAGE_PASS.md",
            f"Phase{self.phase}_STAGE_PASS.md",
        ]
        # 嘗試在樹中找到符合的路徑
        # 匹配：
        #   - Phase2_STAGE_PASS.md (Phase + number + underscore)
        #   - Phase_2_-_架構設計_STAGE_PASS.md (Phase + underscore + number + underscore + text)
        _p = str(self.phase)
        tree_paths = [
            item["path"] for item in self.gh.get_files()
            if re.search(rf"Phase{_p}[^0-9]|Phase_{_p}[^0-9]", item["path"])
            and "STAGE_PASS" in item["path"]
        ]
        # 優先選擇中文格式（路徑較長）
        tree_paths = sorted(tree_paths, key=lambda p: -len(p))
        if not tree_paths:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="CRITICAL",
                title=f"❌ 找不到 Phase{self.phase}_STAGE_PASS.md",
                detail="STAGE_PASS 是 v6.06+ 的強制產出物，缺失代表審計流程被跳過",
                rule_ref="HR-08",
            ))
            return

        sp_path = tree_paths[0]
        content = self.gh.get_file_content(sp_path)
        if not content:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="CRITICAL",
                title="❌ STAGE_PASS 文件無法讀取",
                detail=sp_path,
            ))
            return

        self.result.add(Finding(
            check_id="C2",
            dimension="STAGE_PASS 憑證",
            severity="PASS",
            title=f"✅ STAGE_PASS 文件存在",
            detail=sp_path,
        ))

        # 2a. 必要 H2 章節檢查
        missing_sections = []
        for section in STAGE_PASS_REQUIRED_SECTIONS:
            if section not in content:
                missing_sections.append(section)
        if missing_sections:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="WARNING",
                title=f"⚠️ STAGE_PASS 缺少 {len(missing_sections)} 個必要章節",
                detail=f"缺少：{', '.join(missing_sections)}",
                rule_ref="HR-08",
            ))
        else:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="PASS",
                title="✅ STAGE_PASS 章節結構完整",
                detail=f"包含所有 {len(STAGE_PASS_REQUIRED_SECTIONS)} 個必要章節",
            ))

        # 2a-2. H3 子章節檢查（v7.12 新增）
        missing_subsections = [s for s in STAGE_PASS_SUBSECTIONS if s not in content]
        if missing_subsections:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="WARNING",
                title=f"⚠️ STAGE_PASS 缺少 {len(missing_subsections)} 個子章節",
                detail=f"缺少：{', '.join(missing_subsections)}（v7.12 要求 7H2+10H3=17 sections）",
            ))
        else:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="PASS",
                title="✅ STAGE_PASS 子章節完整（5/5 H3）",
                detail=f"包含：{', '.join(STAGE_PASS_SUBSECTIONS)}",
            ))

        # 2b. Agent B 審查關鍵字
        ab_found = any(kw in content for kw in STAGE_PASS_AGENT_B_KEYWORDS)
        if ab_found:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="PASS",
                title="✅ STAGE_PASS 包含 Agent B 審查記錄",
                detail=f"找到關鍵字：{[kw for kw in STAGE_PASS_AGENT_B_KEYWORDS if kw in content]}",
            ))
        else:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="CRITICAL",
                title="❌ STAGE_PASS 缺少 Agent B 審查記錄",
                detail="找不到 APPROVE / reviewer / 裁決 等關鍵字",
                rule_ref="HR-01",
            ))

        # 2c. 信心分數（支援多種格式：v7.5 用 /100，v7.9+ 用 /10）
        score_match = re.search(r"[*_]*信心分數[*_]*[：:]+\s*(\d+)/(\d+)", content)
        if not score_match:
            score_match = re.search(r"(?:分數|score|confidence)[^:\n]*?(\d{1,3})/(\d+)", content, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
            denominator = int(score_match.group(2))
            # 標準化到 0-100 scale（v7.9+ /10 會乘以 10）
            normalized_score = min(100, (score * 100 // denominator) if denominator != 100 else score)
            sev = "PASS" if normalized_score >= 70 else ("WARNING" if normalized_score >= 50 else "CRITICAL")
            score_display = f"{score}/{denominator}"
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity=sev,
                title=f"{'✅' if sev=='PASS' else '⚠️' if sev=='WARNING' else '❌'} STAGE_PASS 信心分數：{score_display}",
                detail=f"門檻：≥70 (HR-11)",
                rule_ref="HR-11",
            ))
        else:
            self.result.add(Finding(
                check_id="C2",
                dimension="STAGE_PASS 憑證",
                severity="WARNING",
                title="⚠️ 無法從 STAGE_PASS 解析信心分數",
                detail="找不到 XX/100 格式的分數",
            ))

        # 2d. Johnny CONFIRM 狀態
        if "Johnny" in content:
            if re.search(r"Johnny.*?(?:CONFIRM|✅|confirmed)", content, re.IGNORECASE):
                self.result.add(Finding(
                    check_id="C2",
                    dimension="STAGE_PASS 憑證",
                    severity="PASS",
                    title="✅ Johnny HITL 確認記錄存在",
                    detail="找到 Johnny CONFIRM 記錄",
                ))
            elif re.search(r"Johnny.*?(?:⏳|待確認|pending)", content, re.IGNORECASE):
                self.result.add(Finding(
                    check_id="C2",
                    dimension="STAGE_PASS 憑證",
                    severity="WARNING",
                    title="⚠️ Johnny HITL 尚未確認（⏳ 待確認）",
                    detail="STAGE_PASS 中 Johnny 欄位顯示待確認",
                    rule_ref="HR-11",
                ))

    # ── C3: A/B Session 分離驗證 ──────────────────────
    def check_c3_session_separation(self):
        """C3: sessions_spawn.log A/B 不同 session 驗證"""
        content = self._content(["sessions_spawn.log"])
        if not content:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="CRITICAL",
                title="❌ sessions_spawn.log 不存在",
                detail="HR-10 強制要求此檔案存在，缺失代表 A/B 協作無法驗證",
                rule_ref="HR-10",
            ))
            return

        # 解析 line-delimited JSON
        sessions = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError as e:
                # Skip invalid lines with diagnostic logging
                logging.debug(f"Invalid session JSON: {line[:50]}... ({e})")
                # Don't create partial structures; skip entirely

        if not sessions:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="CRITICAL",
                title="❌ sessions_spawn.log 為空或格式無法解析",
                detail=f"內容前100字：{content[:100]}",
                rule_ref="HR-10",
            ))
            return

        self.result.add(Finding(
            check_id="C3",
            dimension="A/B Session 分離",
            severity="PASS",
            title=f"✅ sessions_spawn.log 存在，共 {len(sessions)} 筆記錄",
            detail="",
        ))

        # 提取 roles 和 session_ids
        roles = set()
        session_ids = set()
        for s in sessions:
            if isinstance(s, dict):
                role = s.get("role", "")
                sid = s.get("session_id", "")
                if role:
                    roles.add(role.lower())
                if sid:
                    session_ids.add(sid)

        expected_a = self.spec.get("agent_a", "")
        expected_b = self.spec.get("agent_b", "")

        # 角色檢查
        has_agent_a = expected_a in roles
        has_agent_b = expected_b in roles
        if has_agent_a and has_agent_b:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="PASS",
                title=f"✅ 找到 Agent A ({expected_a}) 和 Agent B ({expected_b}) 記錄",
                detail=f"roles 集合：{roles}",
            ))
        else:
            missing = []
            if not has_agent_a:
                missing.append(f"Agent A ({expected_a})")
            if not has_agent_b:
                missing.append(f"Agent B ({expected_b})")
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="CRITICAL",
                title=f"❌ sessions_spawn.log 缺少角色：{', '.join(missing)}",
                detail=f"找到的 roles：{roles}，期望：{expected_a}, {expected_b}",
                rule_ref="HR-01",
            ))

        # Session ID 唯一性
        if len(session_ids) >= 2:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="PASS",
                title=f"✅ Session ID 有 {len(session_ids)} 個，各不相同（符合 A/B 分離）",
                detail=f"IDs（前20字）：{[str(sid)[:20] for sid in list(session_ids)[:4]]}",
            ))
        elif len(session_ids) == 1:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="CRITICAL",
                title="❌ 所有 session_id 相同（自寫自審嫌疑）",
                detail=f"唯一 session：{list(session_ids)[0]}",
                rule_ref="HR-01",
            ))
        else:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="WARNING",
                title="⚠️ 無法解析 session_id 值",
                detail=f"sessions 原始資料：{sessions[:2]}",
            ))

        # task 欄位是否填寫（Option C: 寬鬆模式 - OpenClaw 系統問題，Framework 無法控制）
        empty_tasks = sum(
            1 for s in sessions
            if isinstance(s, dict) and not s.get("task", "").strip()
        )
        if empty_tasks > 0:
            self.result.add(Finding(
                check_id="C3",
                dimension="A/B Session 分離",
                severity="INFO",
                title=f"ℹ️ {empty_tasks} 筆 session 記錄的 task 欄位為空（OpenClaw 系統限制）",
                detail="sessions_spawn.log 由 OpenClaw 系統產生，Framework 無法控制其格式",
            ))

    # ── C4: DEVELOPMENT_LOG 品質 ─────────────────────
    def check_c4_development_log(self):
        """C4: DEVELOPMENT_LOG 是否有實際命令輸出（非空泛記錄）"""
        # 同時掃描 DEVELOPMENT_LOG 和 sessions_spawn.log
        dev_content = self._content(["DEVELOPMENT_LOG.md"])
        spawn_content = self._content(["sessions_spawn.log"])
        content = (dev_content or "") + "\n" + (spawn_content or "")

        if not content.strip():
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="CRITICAL",
                title="❌ DEVELOPMENT_LOG.md 不存在",
                detail="",
                rule_ref="HR-07",
            ))
            return

        # Phase 相關內容提取（先檢查 DEVELOPMENT_LOG，再檢查 sessions_spawn.log）
        phase_pattern = re.compile(
            rf"##\s*Phase\s*{self.phase}[:\s]", re.IGNORECASE
        )
        has_phase_section = bool(phase_pattern.search(content))

        # sessions_spawn.log 本身就是 Phase 執行的記錄
        has_phase_in_spawn = spawn_content and len(spawn_content.strip()) > 0

        if has_phase_section or has_phase_in_spawn:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="PASS",
                title=f"✅ DEVELOPMENT_LOG 或 sessions_spawn.log 包含 Phase {self.phase} 執行記錄",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="WARNING",
                title=f"⚠️ DEVELOPMENT_LOG 找不到 Phase {self.phase} 專屬段落",
                detail="可能與其他 Phase 混在一起，或段落標題格式不符；sessions_spawn.log 也缺少記錄",
            ))

        # session_id 記錄
        sid_match = re.search(r"session[_-]?id[：:]\s*(\S+)", content, re.IGNORECASE)
        if sid_match:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="PASS",
                title="✅ DEVELOPMENT_LOG 記錄了 session_id",
                detail=f"找到：{sid_match.group(0)[:60]}",
                rule_ref="HR-07",
            ))
        else:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="WARNING",
                title="⚠️ DEVELOPMENT_LOG 未找到 session_id 記錄",
                detail="HR-07 要求記錄，缺失扣 Integrity -15",
                rule_ref="HR-07",
            ))

        # QG 實際輸出證據
        qg_evidence_count = sum(
            1 for pat in QG_EVIDENCE_PATTERNS
            if re.search(pat, content, re.IGNORECASE)
        )
        if qg_evidence_count >= 2:
            matched = [
                pat for pat in QG_EVIDENCE_PATTERNS
                if re.search(pat, content, re.IGNORECASE)
            ]
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="PASS",
                title=f"✅ DEVELOPMENT_LOG 包含 QG 實際輸出證據（{qg_evidence_count}/{len(QG_EVIDENCE_PATTERNS)} 種模式）",
                detail=f"匹配模式：{matched[:3]}",
                rule_ref="HR-02",
            ))
        elif qg_evidence_count == 1:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="WARNING",
                title=f"⚠️ DEVELOPMENT_LOG QG 輸出證據偏少（只有 {qg_evidence_count} 種模式）",
                detail="期望看到 Constitution 分數、ASPICE 結果等多種工具輸出",
                rule_ref="HR-02",
            ))
        else:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="CRITICAL",
                title="❌ DEVELOPMENT_LOG 無可辨識的 QG 工具輸出",
                detail="找不到任何 Constitution/ASPICE/pytest 命令輸出模式，疑似空泛記錄",
                rule_ref="HR-02",
            ))

        # 假通過偵測
        lines = content.splitlines()
        fake_lines = []
        for i, line in enumerate(lines, 1):
            for pat in FAKE_PASS_PATTERNS:
                if re.match(pat, line.strip()):
                    fake_lines.append(f"第{i}行：{line.strip()}")
        if fake_lines:
            self.result.add(Finding(
                check_id="C4",
                dimension="DEVELOPMENT_LOG 品質",
                severity="WARNING",
                title=f"⚠️ 偵測到 {len(fake_lines)} 行疑似空泛通過標記",
                detail="\
".join(fake_lines[:3]),
                evidence="SKILL.md 禁止只寫「✅ 已通過」而無實際命令輸出",
            ))

    # ── C5: Phase 核心文件內容深度 ──────────────────
    def check_c5_content_depth(self):
        """C5: 核心文件的內容品質（SRS FR 數量、章節完整性等）"""
        phase = self.phase

        if phase == 1:
            self._check_srs_depth()
            self._check_spec_tracking_depth()
            self._check_traceability_depth(phase)

        elif phase == 2:
            self._check_sad_depth()

        elif phase in [3, 4]:
            # 檢查測試相關文件
            if phase == 4:
                self._check_test_plan_depth()

        elif phase == 5:
            self._check_baseline_depth()

        elif phase == 6:
            self._check_quality_report_depth()

        elif phase == 7:
            self._check_risk_register_depth()

        elif phase == 8:
            self._check_config_records_depth()

    def _check_srs_depth(self):
        content = self._content(["01-requirements/SRS.md", "SRS.md", "docs/SRS.md"])
        if not content:
            return

        # FR 數量
        fr_matches = re.findall(r"FR-\d+", content)
        fr_count = len(set(fr_matches))
        min_fr = self.spec.get("min_fr_count", 3)
        if fr_count >= min_fr:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ SRS.md 包含 {fr_count} 個功能需求（FR）",
                detail=f"最低要求：{min_fr}，找到：{sorted(set(fr_matches))}",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="CRITICAL" if fr_count == 0 else "WARNING",
                title=f"{'❌' if fr_count==0 else '⚠️'} SRS.md 只有 {fr_count} 個 FR（最低：{min_fr}）",
                detail=f"找到：{sorted(set(fr_matches))}",
            ))

        # 邏輯驗證方法
        logic_count = len(re.findall(r"邏輯驗證方法", content))
        if logic_count >= max(1, fr_count // 2):
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ SRS.md 包含 {logic_count} 個邏輯驗證方法",
                detail="每條 FR 應有對應的邏輯驗證方法",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ SRS.md 邏輯驗證方法不足（{logic_count} 個 vs {fr_count} 個 FR）",
                detail="SKILL.md Phase 1 要求每條 FR 都有邏輯驗證方法",
            ))

        # NFR 存在性
        nfr_matches = re.findall(r"NFR-\d+", content)
        if nfr_matches:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ SRS.md 包含 {len(set(nfr_matches))} 個非功能需求（NFR）",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title="⚠️ SRS.md 未找到 NFR 需求",
                detail="建議包含效能、可用性、可維護性等非功能需求",
            ))

    def _check_spec_tracking_depth(self):
        content = self._content([
            "01-requirements/SPEC_TRACKING.md",
            "SPEC_TRACKING.md",
            "docs/SPEC_TRACKING.md",
        ])
        if not content:
            return
        required_cols = self.spec.get("spec_tracking_required_cols", [])
        missing = [col for col in required_cols if col not in content]
        if not missing:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title="✅ SPEC_TRACKING.md 包含必要欄位",
                detail=f"欄位：{required_cols}",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ SPEC_TRACKING.md 缺少欄位：{missing}",
                detail="",
            ))

    def _check_traceability_depth(self, phase: int):
        content = self._content([
            "01-requirements/TRACEABILITY_MATRIX.md",
            "TRACEABILITY_MATRIX.md",
            "docs/TRACEABILITY_MATRIX.md",
        ])
        if not content:
            return
        required_cols = self.spec.get("traceability_required_cols", [])
        missing = [col for col in required_cols if col not in content]
        if not missing:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title="✅ TRACEABILITY_MATRIX.md 包含必要欄位",
                detail="FR → 模組 對照表存在",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ TRACEABILITY_MATRIX.md 缺少欄位：{missing}",
                detail="",
            ))

    def _check_sad_depth(self):
        content = self._content(["02-architecture/SAD.md", "SAD.md", "docs/SAD.md"])
        if not content:
            return
        required = ["模組", "架構", "FR-"]
        missing = [kw for kw in required if kw not in content]
        if not missing:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title="✅ SAD.md 包含架構設計核心內容",
                detail=f"找到關鍵字：{required}",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ SAD.md 缺少關鍵字：{missing}",
                detail="",
            ))

    def _check_test_plan_depth(self):
        content = self._content(["04-testing/TEST_PLAN.md", "TEST_PLAN.md"])
        if not content:
            return
        tc_count = len(re.findall(r"TC-\d+", content))
        if tc_count >= 3:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ TEST_PLAN.md 包含 {tc_count} 個測試案例（TC）",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING" if tc_count > 0 else "CRITICAL",
                title=f"{'⚠️' if tc_count>0 else '❌'} TEST_PLAN.md 只有 {tc_count} 個 TC（最低：3）",
                detail="",
            ))

    def _check_baseline_depth(self):
        content = self._content(["05-verify/BASELINE.md", "BASELINE.md"])
        if not content:
            return
        h2_count = len(re.findall(r"^## ", content, re.MULTILINE))
        if h2_count >= 7:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ BASELINE.md 有 {h2_count} 個章節（≥7）",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="CRITICAL" if h2_count < 4 else "WARNING",
                title=f"{'❌' if h2_count<4 else '⚠️'} BASELINE.md 只有 {h2_count} 個章節（需要 7 個）",
                detail="SKILL.md §Phase 5 要求 7 章節：概述、功能基線、品質基線、效能基線、問題登錄、變更記錄、驗收簽收",
            ))

    def _check_quality_report_depth(self):
        content = self._content([
            "06-quality/QUALITY_REPORT.md", "QUALITY_REPORT.md"
        ])
        if not content:
            return
        h2_count = len(re.findall(r"^## ", content, re.MULTILINE))
        if h2_count >= 7:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ QUALITY_REPORT.md 有 {h2_count} 個章節（≥7）",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ QUALITY_REPORT.md 只有 {h2_count} 個章節（需要 7）",
                detail="",
            ))

    def _check_risk_register_depth(self):
        content = self._content([
            "07-risk/RISK_REGISTER.md", "RISK_REGISTER.md"
        ])
        if not content:
            return
        risk_count = len(re.findall(r"(?:HIGH|MEDIUM|LOW|🔴|🟡|🟢)", content))
        if risk_count >= 3:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ RISK_REGISTER.md 包含 {risk_count} 個風險評級記錄",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ RISK_REGISTER.md 風險記錄偏少（{risk_count} 個）",
                detail="SKILL.md §Phase 7 要求五維度風險識別，每個維度至少 1 個",
            ))

    def _check_config_records_depth(self):
        content = self._content([
            "08-config/CONFIG_RECORDS.md", "CONFIG_RECORDS.md"
        ])
        if not content:
            return
        h2_count = len(re.findall(r"^## ", content, re.MULTILINE))
        if h2_count >= 8:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="PASS",
                title=f"✅ CONFIG_RECORDS.md 有 {h2_count} 個章節（≥8）",
                detail="",
            ))
        else:
            self.result.add(Finding(
                check_id="C5",
                dimension="文件內容深度",
                severity="WARNING",
                title=f"⚠️ CONFIG_RECORDS.md 只有 {h2_count} 個章節（需要 8）",
                detail="",
            ))

    # ── C6: Commit 時間線分析 ────────────────────────
    def check_c6_commit_timeline(self):
        """C6: GitHub Commit 時間線合理性"""
        commits = self.gh.get_commits(per_page=30)
        if not commits:
            self.result.add(Finding(
                check_id="C6",
                dimension="Commit 時間線",
                severity="WARNING",
                title="⚠️ 無法取得 commit 記錄",
                detail="",
            ))
            return

        # Phase 相關 commit
        phase_keywords = [
            f"phase {self.phase}", f"phase{self.phase}",
            f"Phase {self.phase}", f"Phase{self.phase}",
            f"Phase_{self.phase}", f"STAGE_PASS",
        ]
        phase_commits = [
            c for c in commits
            if isinstance(c, dict) and any(kw.lower() in c.get("commit", {}).get("message", "").lower()
                   for kw in phase_keywords)
        ]

        self.result.add(Finding(
            check_id="C6",
            dimension="Commit 時間線",
            severity="INFO",
            title=f"ℹ️ 找到 {len(phase_commits)} 個 Phase {self.phase} 相關 commit",
            detail="\n".join([
                f"  {c.get('sha','?')[:7]} "
                f"{c.get('commit',{}).get('author',{}).get('date','?')[:16]} "
                f"| {c.get('commit',{}).get('message','')[:60]}"
                for c in phase_commits[:5]
            ]),
        ))

        if len(phase_commits) >= 2:
            # 計算最早和最晚的 commit 時間差
            times = []
            for c in phase_commits:
                ts = c.get("commit", {}).get("author", {}).get("date", "")
                if ts:
                    try:
                        times.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                    except ValueError:
                        logging.debug(f"Invalid ISO timestamp format: {ts}")
            if len(times) >= 2:
                times.sort()
                duration_min = (times[-1] - times[0]).total_seconds() / 60
                min_required = self.spec.get("min_duration_minutes", 5)
                if duration_min >= min_required:
                    self.result.add(Finding(
                        check_id="C6",
                        dimension="Commit 時間線",
                        severity="PASS",
                        title=f"✅ Phase {self.phase} commit 跨度 {duration_min:.0f} 分鐘（最低：{min_required} 分鐘）",
                        detail=f"首 commit：{times[0].strftime('%H:%M')} → 末 commit：{times[-1].strftime('%H:%M')}",
                    ))
                else:
                    self.result.add(Finding(
                        check_id="C6",
                        dimension="Commit 時間線",
                        severity="WARNING",
                        title=f"⚠️ Phase {self.phase} commit 跨度只有 {duration_min:.0f} 分鐘（最低：{min_required} 分鐘）",
                        detail="執行時間過短，可能未完整執行所有步驟",
                    ))

        # 重複 commit 檢查（多次 fix 代表迭代修復，是正常的）
        fix_commits = [
            c for c in phase_commits
            if isinstance(c, dict) and "fix" in c.get("commit", {}).get("message", "").lower()
        ]
        if fix_commits:
            self.result.add(Finding(
                check_id="C6",
                dimension="Commit 時間線",
                severity="INFO",
                title=f"ℹ️ 有 {len(fix_commits)} 個修復 commit（顯示迭代過程，屬正常）",
                detail="\n".join([
                    f"  {c.get('sha','?')[:7]}: {c.get('commit',{}).get('message','')[:60]}"
                    for c in fix_commits[:3]
                ]),
            ))

    # ── C7: Claims 交叉驗證 ──────────────────────────
    def check_c7_claims_crosscheck(self):
        """C7: 聲稱分數 vs 文件實際內容的交叉驗證"""
        # 從 STAGE_PASS 提取聲稱的 Constitution 分數
        # 優先選擇中文格式（路徑較長）
        phase_patterns = [
            f"Phase{self.phase}_",
            f"Phase_{self.phase}_",
            f"Phase_{self.phase}-",
        ]
        sp_paths = sorted([
            item["path"] for item in self.gh.get_files()
            if any(pat in item["path"] for pat in phase_patterns)
            and "STAGE_PASS" in item["path"]
        ], key=lambda p: -len(p))
        if not sp_paths:
            return

        sp_content = self.gh.get_file_content(sp_paths[0]) or ""
        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 從 STAGE_PASS 抓 Constitution 聲稱值（區分「信心分數」和「Constitution 分數」）
        const_claimed = None
        for pat in [
            # 優先匹配 "Constitution Score: ✅ 85.7%" 或 "Constitution Score: 85.7%"
            r"Constitution\s+Score.*?([\d.]+)%",
            # 備用：只有 "Constitution" 開頭的行（但排除「信心分數」）
            r"(?:^|\n)Constitution[^信心].*?([\d.]+)%",
        ]:
            m = re.search(pat, sp_content, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    const_claimed = float(m.group(1))
                    break
                except ValueError:
                    logging.debug(f"Failed to parse Constitution from '{m.group(1)}'")
                    pass

        # 從 DEVELOPMENT_LOG 抓 Constitution 值
        const_log = None
        for pat in [
            r"Constitution\s+Score.*?([\d.]+)%",
            r"(?:^|\n)Constitution[^信心].*?([\d.]+)%",
        ]:
            m = re.search(pat, dev_content, re.IGNORECASE | re.MULTILINE)
            if m:
                try:
                    const_log = float(m.group(1))
                    break
                except ValueError:
                    logging.debug(f"Failed to parse Constitution from DEVELOPMENT_LOG: '{m.group(1)}'")
                    pass

        if const_claimed is not None and const_log is not None:
            diff = abs(const_claimed - const_log)
            if diff < 5:
                self.result.add(Finding(
                    check_id="C7",
                    dimension="Claims 交叉驗證",
                    severity="PASS",
                    title=f"✅ Constitution 分數一致：STAGE_PASS={const_claimed}% ≈ LOG={const_log}%",
                    detail=f"差異：{diff:.1f}%（允許誤差：5%）",
                ))
            else:
                self.result.add(Finding(
                    check_id="C7",
                    dimension="Claims 交叉驗證",
                    severity="WARNING",
                    title=f"⚠️ Constitution 分數不一致：STAGE_PASS={const_claimed}% vs LOG={const_log}%",
                    detail=f"差異：{diff:.1f}%，可能是不同時間點的分數",
                    rule_ref="HR-09",
                ))
        elif const_claimed is not None:
            self.result.add(Finding(
                check_id="C7",
                dimension="Claims 交叉驗證",
                severity="INFO",
                title=f"ℹ️ STAGE_PASS 聲稱 Constitution={const_claimed}%，但 DEVELOPMENT_LOG 找不到對應數值",
                detail="無法做交叉驗證",
            ))

        # 交付物數量聲稱 vs 實際
        claimed_count_match = re.search(r"(\d+)/(\d+)\s*(?:通過|PASS|存在)", sp_content)
        if claimed_count_match:
            claimed_pass = int(claimed_count_match.group(1))
            claimed_total = int(claimed_count_match.group(2))
            self.result.add(Finding(
                check_id="C7",
                dimension="Claims 交叉驗證",
                severity="INFO",
                title=f"ℹ️ STAGE_PASS 聲稱 {claimed_pass}/{claimed_total} 項目通過",
                detail="（與 C1 交付物檢查結果相互印證）",
            ))

    # ── C8: Integrity Tracker 狀態 ───────────────────
    def check_c8_integrity(self):
        """C8: .integrity_tracker.json 誠信分數（如存在）"""
        content = self._content([".integrity_tracker.json"])
        if not content:
            self.result.add(Finding(
                check_id="C8",
                dimension="Integrity Tracker",
                severity="INFO",
                title="ℹ️ .integrity_tracker.json 不存在於 GitHub",
                detail="可能是本地工具，未上傳至 GitHub（可接受）",
            ))
            return

        try:
            data = json.loads(content)
            score = data.get("integrity_score", 100)
            violations = data.get("violations", [])

            if score >= 80:
                sev = "PASS"
                icon = "✅"
            elif score >= 50:
                sev = "WARNING"
                icon = "⚠️"
            else:
                sev = "CRITICAL"
                icon = "❌"

            self.result.add(Finding(
                check_id="C8",
                dimension="Integrity Tracker",
                severity=sev,
                title=f"{icon} Integrity Score：{score}/100（{['LOW_TRUST','PARTIAL_TRUST','FULL_TRUST'][0 if score<50 else 1 if score<80 else 2]}）",
                detail=f"違規記錄：{len(violations)} 筆",
                rule_ref="HR-09",
            ))

            if violations:
                self.result.add(Finding(
                    check_id="C8",
                    dimension="Integrity Tracker",
                    severity="WARNING",
                    title=f"⚠️ Integrity 違規記錄：",
                    detail="\
".join([
                        f"  - {v.get('type','?')}: {v.get('details','')[:60]}"
                        for v in violations[:5]
                    ]),
                ))
        except json.JSONDecodeError:
            self.result.add(Finding(
                check_id="C8",
                dimension="Integrity Tracker",
                severity="WARNING",
                title="⚠️ .integrity_tracker.json 格式無法解析",
                detail=content[:100],
            ))

    # ── C9: Traceability Annotation 覆蓋率 ──────────────
    def check_c9_traceability_annotations(self):
        """C9: v6.15 TH-16/TH-17 — @FR/@covers annotation 覆蓋率（Phase 3/4 專用）"""
        if self.phase == 3:
            self._check_fr_annotations()
        elif self.phase == 4:
            self._check_covers_annotations()
        else:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="INFO",
                title=f"ℹ️ C9 Annotation 檢查不適用於 Phase {self.phase}（僅限 Phase 3/4）",
                detail="TH-16 (Phase 3) 和 TH-17 (Phase 4) 才需要 @FR/@covers annotation",
            ))

    def _check_fr_annotations(self):
        """Phase 3: 掃描 src/ 中 Python/JS 檔案，驗證 @FR annotation 存在"""
        tree = self.gh.get_files()
        src_files = [
            item["path"] for item in tree
            if any(item["path"].startswith(pfx) for pfx in ["src/", "app/", "03-development/src/"])
            and item["path"].endswith((".py", ".ts", ".js"))
            and not item["path"].endswith(("__init__.py", ".test.py", ".spec.ts"))
        ]
        if not src_files:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="WARNING",
                title="⚠️ 找不到可掃描的源代碼檔案（src/、app/ 目錄）",
                detail="TH-16 需要代碼檔案含 @FR annotation，但找不到 .py/.ts/.js 檔案",
                rule_ref="TH-16",
            ))
            return

        sample = src_files[:15]  # 最多掃描 15 個檔案
        annotated = []
        missing = []
        for path in sample:
            content = self.gh.get_file_content(path)
            if content and (
                "@FR:" in content
                or re.search(r"\[FR-\d+\]", content)
            ):
                annotated.append(path)
            elif content:
                missing.append(path)

        total = len(annotated) + len(missing)
        rate = len(annotated) / total if total > 0 else 0

        if rate >= 0.9:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="PASS",
                title=f"✅ @FR annotation 覆蓋率：{rate:.0%}（{len(annotated)}/{total} 個檔案）",
                detail=f"TH-16 要求代碼 ↔ SAD 映射（抽樣 {total} 個檔案）",
                rule_ref="TH-16",
            ))
        elif rate >= 0.5:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="WARNING",
                title=f"⚠️ @FR annotation 覆蓋率偏低：{rate:.0%}（{len(annotated)}/{total} 個檔案）",
                detail=f"缺少 @FR 的檔案（前5個）：{missing[:5]}",
                rule_ref="TH-16",
            ))
        else:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="CRITICAL",
                title=f"❌ @FR annotation 嚴重不足：{rate:.0%}（{len(annotated)}/{total} 個檔案）",
                detail=f"v6.15 SKILL.md §Phase 3 要求每個主要類別/函式含 @FR，用於 trace-check TH-16",
                rule_ref="TH-16",
            ))

        if missing:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="INFO",
                title=f"ℹ️ 缺少 @FR annotation 的檔案（共 {len(missing)} 個）",
                detail="\
".join(f"  - {p}" for p in missing[:5]),
            ))

    def _check_covers_annotations(self):
        """Phase 4: 掃描 tests/ 中測試檔案，驗證 @covers annotation 存在"""
        tree = self.gh.get_files()
        test_files = [
            item["path"] for item in tree
            if any(item["path"].startswith(pfx) for pfx in ["tests/", "test/", "04-testing/", "03-development/tests/"])
            and item["path"].endswith((".py", ".ts", ".js"))
        ]
        if not test_files:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="WARNING",
                title="⚠️ 找不到測試檔案（tests/、test/ 目錄）",
                detail="TH-17 需要測試檔案含 @covers annotation",
                rule_ref="TH-17",
            ))
            return

        sample = test_files[:15]
        annotated = []
        missing = []
        for path in sample:
            content = self.gh.get_file_content(path)
            if content and "@covers:" in content:
                annotated.append(path)
            elif content:
                missing.append(path)

        total = len(annotated) + len(missing)
        rate = len(annotated) / total if total > 0 else 0

        if rate >= 0.9:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="PASS",
                title=f"✅ @covers annotation 覆蓋率：{rate:.0%}（{len(annotated)}/{total} 個測試檔案）",
                detail=f"TH-17 要求 FR ↔ 測試映射（抽樣 {total} 個檔案）",
                rule_ref="TH-17",
            ))
        elif rate >= 0.5:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="WARNING",
                title=f"⚠️ @covers annotation 覆蓋率偏低：{rate:.0%}（{len(annotated)}/{total} 個測試檔案）",
                detail=f"缺少 @covers 的測試（前5個）：{missing[:5]}",
                rule_ref="TH-17",
            ))
        else:
            self.result.add(Finding(
                check_id="C9",
                dimension="Traceability Annotation",
                severity="CRITICAL",
                title=f"❌ @covers annotation 嚴重不足：{rate:.0%}（{len(annotated)}/{total} 個測試檔案）",
                detail="v6.15 SKILL.md §Phase 4 要求每個測試函式含 @covers + @type，用於 trace-check TH-17",
                rule_ref="TH-17",
            ))

    # ── C10: Runtime Metrics 狀態（v6.15 新增）─────────
    def check_c10_runtime_metrics(self):
        """C10: v6.15 — .methodology/state.json 存在且無異常狀態"""
        content = self._content([".methodology/state.json"])
        if not content:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="INFO",
                title="ℹ️ .methodology/state.json 不存在於 GitHub",
                detail="v6.15 建議上傳 state.json 以供外部稽核追蹤 Runtime Metrics（HR-12/13/14 觸發紀錄）",
            ))
            return

        try:
            state = json.loads(content)
        except json.JSONDecodeError:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="WARNING",
                title="⚠️ .methodology/state.json 格式無法解析",
                detail=content[:150],
            ))
            return

        phase_state = state.get("phase_state", {})
        status = phase_state.get("status", "UNKNOWN")
        ab_rounds = phase_state.get("ab_rounds", 0)
        blocks = phase_state.get("blocks", 0)
        integrity = phase_state.get("integrity_score", 100)

        # 狀態健康度
        if status == "FREEZE":
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="CRITICAL",
                title=f"❌ Phase 狀態為 FREEZE（HR-14 已觸發）",
                detail=f"Integrity Score={integrity}，低於 40 閾值，專案已凍結",
                rule_ref="HR-14",
            ))
        elif status == "PAUSE":
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="WARNING",
                title=f"⚠️ Phase 狀態為 PAUSE（HR-12 或 HR-13 已觸發）",
                detail=f"ab_rounds={ab_rounds}，等待人工裁決",
                rule_ref="HR-12",
            ))
        elif status in ("RUNNING", "COMPLETED"):
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="PASS",
                title=f"✅ Runtime Metrics 正常（status={status}）",
                detail=f"ab_rounds={ab_rounds}, blocks={blocks}, integrity={integrity}",
            ))
        else:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="INFO",
                title=f"ℹ️ 未知 Phase 狀態：{status}（可能 state.json 不存在或格式問題）",
                detail="預期值：RUNNING, COMPLETED, PAUSE, FREEZE；若無 state.json，該檢查不適用",
            ))

        # HR-12 A/B 輪次預警（5 為強制 PAUSE 閾值）
        if ab_rounds >= 5:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="CRITICAL",
                title=f"❌ A/B 審查輪次達 {ab_rounds} 輪（≥5 觸發 HR-12 PAUSE）",
                detail="代表審查反覆不通過，需要人工介入確認",
                rule_ref="HR-12",
            ))
        elif ab_rounds >= 3:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="WARNING",
                title=f"⚠️ A/B 審查輪次偏高：{ab_rounds} 輪（閾值：5）",
                detail="建議檢查是否存在系統性問題",
                rule_ref="HR-12",
            ))

        # HR-14 Integrity 預警
        if integrity < 40:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="CRITICAL",
                title=f"❌ Integrity Score={integrity} < 40（HR-14 凍結閾值）",
                detail="專案應被 FREEZE，全面審計後才能繼續",
                rule_ref="HR-14",
            ))
        elif integrity < 60:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="WARNING",
                title=f"⚠️ Integrity Score={integrity}，低於 60 預警線",
                detail="接近 HR-14 凍結閾值（40），建議檢查違規記錄",
                rule_ref="HR-14",
            ))

        # v7.5 新增: HR-13 煞車狀態檢查
        hr13_triggered = state.get("hr13_triggered", False)
        hr13_remaining = state.get("hr13_remaining_minutes")
        estimated = state.get("estimated_minutes")
        start_time = state.get("start_time")
        if hr13_triggered:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="WARNING",
                title=f"⚠️ HR-13 已觸發：Phase 執行時間超過預估 ×3",
                detail=f"預估={estimated}min，剩餘={hr13_remaining}min，開始時間={start_time}",
                rule_ref="HR-13",
            ))
        elif estimated:
            self.result.add(Finding(
                check_id="C10",
                dimension="Runtime Metrics",
                severity="PASS",
                title=f"✅ HR-13 煞車未觸發（預估={estimated}min）",
                detail=f"start_time={start_time}",
            ))

    # ── C11: Verify_Agent 執行記錄（v6.21 新增）──────────
    def check_c11_verify_agent(self):
        """C11: v6.21 — Phase 3+ 必須有 Verify_Agent 第三方驗證記錄"""
        if self.phase < 3:
            self.result.add(Finding(
                check_id="C11",
                dimension="Verify_Agent 記錄",
                severity="INFO",
                title=f"ℹ️ C11 Verify_Agent 檢查不適用於 Phase {self.phase}（僅限 Phase 3+）",
                detail="Verify_Agent 在 Phase 3+ 且 Agent B < 80 或 Agent A 自評差異 > 20 時觸發",
            ))
            return

        # 搜尋 DEVELOPMENT_LOG 和 STAGE_PASS 中的 Verify_Agent 記錄
        verify_keywords = re.compile(
            r"Verify_Agent|verify_agent|Verifier|VERIFIER|第三方驗證",
            re.IGNORECASE
        )

        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 找到當前 Phase 的 STAGE_PASS 內容
        phase_patterns = [f"Phase{self.phase}_", f"Phase_{self.phase}_", f"Phase_{self.phase}-"]
        sp_paths = sorted([
            item["path"] for item in self.gh.get_files()
            if any(pat in item["path"] for pat in phase_patterns)
            and "STAGE_PASS" in item["path"]
        ], key=lambda p: -len(p))
        sp_content = self.gh.get_file_content(sp_paths[0]) if sp_paths else ""

        combined = (dev_content or "") + (sp_content or "")
        found = bool(verify_keywords.search(combined))

        if found:
            match = verify_keywords.search(combined)
            self.result.add(Finding(
                check_id="C11",
                dimension="Verify_Agent 記錄",
                severity="PASS",
                title="✅ 找到 Verify_Agent 第三方驗證記錄",
                detail=f"關鍵字：{match.group(0) if match else 'Verify_Agent'}（符合 v6.21 §Verify_Agent 流程）",
            ))
        else:
            self.result.add(Finding(
                check_id="C11",
                dimension="Verify_Agent 記錄",
                severity="INFO",
                title=f"ℹ️ Phase {self.phase} 未找到 Verify_Agent 執行記錄",
                detail="Verify_Agent 是 v6.21+ 的功能；若使用更早版本，該檢查不適用。"
                       "若使用 v6.21+，建議在 DEVELOPMENT_LOG 中記錄「未觸發原因」",
            ))

        # v6.21 額外檢查：STAGE_PASS 是否包含 confidence 和 summary 結構化欄位
        if sp_content:
            missing_fields = [
                f for f in STAGE_PASS_STRUCTURED_FIELDS if f not in sp_content
            ]
            if missing_fields:
                self.result.add(Finding(
                    check_id="C11",
                    dimension="Verify_Agent 記錄",
                    severity="WARNING",
                    title=f"⚠️ STAGE_PASS 缺少 v6.21 結構化欄位：{', '.join(missing_fields)}",
                    detail="v6.21 要求 Agent 回傳包含 confidence（1-10）和 summary（50字內摘要）",
                ))
            else:
                self.result.add(Finding(
                    check_id="C11",
                    dimension="Verify_Agent 記錄",
                    severity="PASS",
                    title="✅ STAGE_PASS 包含 v6.21 結構化欄位（confidence + summary）",
                    detail="",
                ))

    # ── C12: Citations 品質（HR-15, v7.5 新增）──────────
    def check_c12_citations_quality(self):
        """C12: v7.5 — citations 必須含行號 + artifact_verification，缺少則 Integrity -15
        v7.5 新增：對齊 verify_citations.py 的精確格式 (SRS.md#L23-L45)"""
        # 收集所有可能含 citations 的文件
        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 搜尋 STAGE_PASS
        phase_patterns = [f"Phase{self.phase}_", f"Phase_{self.phase}_", f"Phase_{self.phase}-"]
        sp_paths = sorted([
            item["path"] for item in self.gh.get_files()
            if any(pat in item["path"] for pat in phase_patterns)
            and "STAGE_PASS" in item["path"]
        ], key=lambda p: -len(p))
        sp_content = self.gh.get_file_content(sp_paths[0]) if sp_paths else ""

        combined = (dev_content or "") + "\n" + (sp_content or "")

        if not combined.strip():
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="WARNING",
                title="⚠️ 無法取得文件內容進行 citations 檢查",
                detail="DEVELOPMENT_LOG 和 STAGE_PASS 均為空",
            ))
            return

        # ── v7.5 精確 citation 格式（對齊 verify_citations.py）──
        # v8.0 標準格式: 檔案#L行號 或 檔案#L起始-L結束
        # e.g., SRS.md#L23, SAD.md#L45-L67, TEST_PLAN.md#L10-L20
        structured_citation = re.compile(
            r"[A-Z_]+\.md#L\d+(?:-L?\d+)?",
            re.IGNORECASE,
        )
        structured_hits = structured_citation.findall(combined)

        # Citations: 行（verify_citations.py 的 CITATION_PATTERN）
        citations_line = re.compile(
            r"Citations:\s*(?:[A-Z_]+\.md#L\d+(?:-L?\d+)?(?:\s*,\s*)?)+",
            re.IGNORECASE,
        )
        has_citations_line = bool(citations_line.search(combined))

        # 寬鬆行號引用（向後相容 v6.54 舊格式）
        loose_line_ref = re.compile(
            r"[Ll]ine\s*\d+|L\d+|第\d+行|:\d+(?:\s|$)|行號\s*[:：]?\s*\d+",
        )
        has_loose_refs = bool(loose_line_ref.search(combined))

        # artifact_verification 模式
        artifact_pattern = re.compile(
            r"artifact_verification|artifact.verification|驗證結果|verification_result|verify_result",
            re.IGNORECASE,
        )
        has_artifact_verify = bool(artifact_pattern.search(combined))

        # verify_citations.py 執行證據
        verify_tool_pattern = re.compile(
            r"verify_citations\.py|citation_enforcer\.py|PASS:\s*\d+\s*files.*?Citations",
            re.IGNORECASE,
        )
        has_verify_tool = bool(verify_tool_pattern.search(combined))

        # ── 判定邏輯 ──
        if structured_hits and has_artifact_verify:
            detail = f"精確引用 {len(structured_hits)} 處（{', '.join(structured_hits[:5])}）"
            if has_verify_tool:
                detail += " + verify_citations.py 已執行"
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="PASS",
                title="✅ Citations 採用 v8.0 標準格式（單行 Artifact.md#L23 或 範圍 L23-L45）且包含 artifact_verification",
                detail=detail,
            ))
        elif has_loose_refs and has_artifact_verify:
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="WARNING",
                title="⚠️ Citations 含行號但未採用 v8.0 標準格式（應為 檔案#L行號 或 檔案#L起始-L結束）",
                detail="v8.0 建議格式（兩者皆可）：SRS.md#L23 （單行）或 SRS.md#L23-L45 （範圍）, SAD.md#L67 等",
                rule_ref="HR-15",
            ))
        elif not has_loose_refs and not has_artifact_verify:
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="CRITICAL",
                title="❌ Citations 缺少行號引用與 artifact_verification（違反 HR-15, Integrity -15）",
                detail="v8.0 HR-15: citations 必須採用標準格式（檔案#L行號 或 L起始-L結束）+ artifact_verification",
                rule_ref="HR-15",
            ))
        else:
            # HR-15 Layer 3 是「建議」不是「強制」，降級為 INFO 而非 CRITICAL
            missing = []
            if not has_loose_refs and not structured_hits:
                missing.append("行號引用")
            if not has_artifact_verify:
                missing.append("artifact_verification")
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="WARNING",
                title=f"⚠️ Citations 缺少：{', '.join(missing)}（HR-15 部分不符）",
                detail="v8.0 HR-15: citations 必須採用標準格式（檔案#L行號 或 L起始-L結束）+ artifact_verification，缺少則 Integrity -15",
                rule_ref="HR-15",
            ))

        # ── v7.5 新增：檢查 verify_citations.py 是否已執行 ──
        # HR-15 Layer 3（verify tool）是「建議」不是「強制」，降級為 INFO
        if self.phase >= 3 and not has_verify_tool:
            self.result.add(Finding(
                check_id="C12",
                dimension="Citations 品質",
                severity="INFO",
                title="⚠️ Phase 3+ 未偵測到 verify_citations.py / citation_enforcer.py 執行記錄",
                detail="v8.0 HR-15 Layer 3: Phase 3+ 應執行 quality_gate/verify_citations.py 自動驗證",
                rule_ref="HR-15",
            ))

    # ── C13: FORBIDDEN 模式偵測（v7.5 新增）──────────
    def check_c13_forbidden_patterns(self):
        """C13: v7.5 — 偵測 SKILL.md 明確禁止的模式（ellipsis in code, fabrication 等）"""
        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 搜集 Phase 相關的所有 .py 檔案（若有）
        # Phase 3 (實作階段) 特別掃描 src/app/03-development 下的檔案
        if self.phase == 3:
            code_prefixes = ["src/", "app/", "03-development/", "03-implementation/"]
            code_files = [
                item["path"] for item in self.gh.get_files()
                if item["path"].endswith(".py")
                and any(item["path"].startswith(pfx) for pfx in code_prefixes)
            ]
        else:
            phase_patterns = [f"Phase{self.phase}", f"Phase_{self.phase}", f"phase{self.phase}"]
            code_files = [
                item["path"] for item in self.gh.get_files()
                if item["path"].endswith(".py")
                and any(pat.lower() in item["path"].lower() for pat in phase_patterns)
            ]

        violations = []

        # 1. 檢查 ellipsis_in_code：程式碼中的 ... 省略
        ellipsis_pattern = re.compile(r"^\s*\.\.\.\s*$", re.MULTILINE)
        for fpath in code_files[:10]:  # 限制掃描數量
            content = self.gh.get_file_content(fpath) or ""
            matches = ellipsis_pattern.findall(content)
            if matches:
                violations.append(f"ellipsis_in_code: {fpath} ({len(matches)} 處)")

        # 2. 檢查 DEVELOPMENT_LOG 中的 fabricated_content 指標
        fabrication_indicators = re.compile(
            r"unable_to_proceed(?!.*原因|.*reason|.*because)|"
            r"(?:假設|假定|推測).*(?:完成|通過|成功)(?!.*驗證)",
            re.IGNORECASE,
        )
        fab_matches = fabrication_indicators.findall(dev_content)
        if fab_matches:
            violations.append(f"fabricated_content: DEVELOPMENT_LOG 含 {len(fab_matches)} 處可疑標記")

        # 3. 檢查 subagent_inheriting_context（v7.5 新增）
        inherit_pattern = re.compile(
            r"(?:inherit|繼承).*(?:context|上下文|parent)",
            re.IGNORECASE,
        )
        if inherit_pattern.search(dev_content):
            violations.append("subagent_inheriting_context: Subagent 可能繼承父級上下文")

        if not violations:
            self.result.add(Finding(
                check_id="C13",
                dimension="FORBIDDEN 模式",
                severity="PASS",
                title="✅ 未偵測到 SKILL.md FORBIDDEN 模式違規",
                detail="已檢查：ellipsis_in_code, fabricated_content, subagent_inheriting_context",
            ))
        else:
            for v in violations:
                constraint_key = v.split(":")[0].strip()
                penalty = dict(NEGATIVE_CONSTRAINTS).get(
                    constraint_key, ("未知違規", -10)
                )
                self.result.add(Finding(
                    check_id="C13",
                    dimension="FORBIDDEN 模式",
                    severity="CRITICAL" if "fabricated" in v else "WARNING",
                    title=f"⚠️ FORBIDDEN 違規：{v}",
                    detail=f"NEGATIVE_CONSTRAINT: {penalty[0] if isinstance(penalty, tuple) else penalty}",
                ))

    # ── C14: run-phase 入口驗證（v7.5 新增）──────────────
    def check_c14_run_phase_entry(self):
        """C14: v7.5 — 驗證使用 python cli.py run-phase 標準入口"""
        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 檢查 run-phase 使用
        run_phase_pattern = re.compile(
            r"python\s+cli\.py\s+run-phase|run-phase.*--phase\s*\d+",
            re.IGNORECASE,
        )
        has_run_phase = bool(run_phase_pattern.search(dev_content))

        # 檢查 Pre-flight 執行
        preflight_pattern = re.compile(
            r"pre-flight|pre_flight|PRE-FLIGHT|preflight",
            re.IGNORECASE,
        )
        has_preflight = bool(preflight_pattern.search(dev_content))

        if has_run_phase and has_preflight:
            self.result.add(Finding(
                check_id="C14",
                dimension="run-phase 入口驗證",
                severity="PASS",
                title="✅ 使用標準入口 python cli.py run-phase + Pre-flight 驗證",
                detail="符合 v8.0 §run-phase 單一入口點原則",
            ))
        elif has_run_phase:
            self.result.add(Finding(
                check_id="C14",
                dimension="run-phase 入口驗證",
                severity="WARNING",
                title="⚠️ 使用 run-phase 但未偵測到 Pre-flight 執行",
                detail="v8.0 要求 Pre-flight checks 在 Phase 進入前執行",
            ))
        else:
            self.result.add(Finding(
                check_id="C14",
                dimension="run-phase 入口驗證",
                severity="WARNING",
                title="⚠️ 未使用 python cli.py run-phase 標準入口",
                detail="v8.0 建議所有 Phase 執行都應使用標準入口點以便 FSM 狀態檢查",
            ))

    # ── C15: artifact_verification 強制欄位（v7.5 增強）──────────────
    def check_c15_artifact_verification(self):
        """C15: v7.5 — artifact_verification 欄位必須出現在所有 Phase 3+ 產物"""
        if self.phase < 3:
            self.result.add(Finding(
                check_id="C15",
                dimension="artifact_verification 強制欄位",
                severity="INFO",
                title="ℹ️ artifact_verification 檢查不適用於 Phase 1-2",
                detail="",
            ))
            return

        dev_content = self._content(["DEVELOPMENT_LOG.md"]) or ""

        # 使用樹掃描尋找 STAGE_PASS（與 C2/C7/C11/C12 一致）
        _p = str(self.phase)
        sp_paths = sorted([
            item["path"] for item in self.gh.get_files()
            if re.search(rf"Phase{_p}[^0-9]|Phase_{_p}[^0-9]", item["path"])
            and "STAGE_PASS" in item["path"]
        ], key=lambda p: -len(p))
        sp_content = (self.gh.get_file_content(sp_paths[0]) if sp_paths else None) or ""

        combined = dev_content + "\n" + sp_content

        # 檢查 artifact_verification JSON 結構
        artifact_verify_pattern = re.compile(
            r'"artifact_verification"\s*:\s*\{[^}]+\}',
            re.IGNORECASE | re.DOTALL,
        )
        has_artifact_field = bool(artifact_verify_pattern.search(combined))

        # 檢查文字格式的 artifact_verification
        text_verify_pattern = re.compile(
            r"artifact_verification|已讀.*(?:SRS|SAD|SPEC|ARCH)\.md|verified.*artifact",
            re.IGNORECASE,
        )
        has_text_verify = bool(text_verify_pattern.search(combined))

        if has_artifact_field or has_text_verify:
            self.result.add(Finding(
                check_id="C15",
                dimension="artifact_verification 強制欄位",
                severity="PASS",
                title="✅ 包含 artifact_verification 記錄",
                detail="符合 v8.0 §HR-15 強制驗證欄位",
            ))
        else:
            self.result.add(Finding(
                check_id="C15",
                dimension="artifact_verification 強制欄位",
                severity="CRITICAL",
                title="❌ artifact_verification 強制欄位缺失",
                detail="v8.0 HR-15: Phase 3+ 必須包含 artifact_verification 記錄（Integrity -15）",
                rule_ref="HR-15",
            ))

    # ── C16: Phase Prerequisites 往前檢查（v7.57 新增）──────────────
    def check_c16_phase_prerequisites(self):
        """C16: v7.57 — 檢查前階段產出物是否齊全"""
        PHASE_PREREQUISITES = {
            1: [],
            2: ["SRS.md", "01-requirements/SRS.md"],
            3: ["SRS.md", "01-requirements/SRS.md", "02-architecture/SAD.md", ".methodology/fr_mapping.json"],
            4: ["SRS.md", "01-requirements/SRS.md", "02-architecture/SAD.md", ".methodology/fr_mapping.json", ".methodology/SAB.json"],
            5: ["SRS.md", "01-requirements/SRS.md", "02-architecture/SAD.md", ".methodology/SAB.json", "04-testing/TEST_PLAN.md"],
            6: ["SRS.md", "01-requirements/SRS.md", "02-architecture/SAD.md", ".methodology/SAB.json", "04-testing/TEST_PLAN.md", "05-verify/BASELINE.md"],
            7: ["06-quality/QUALITY_REPORT.md"],
            8: ["08-config/CONFIG_RECORDS.md", "08-config/requirements.lock"],
        }

        prereqs = PHASE_PREREQUISITES.get(self.phase, [])
        if not prereqs:
            self.result.add(Finding(
                check_id="C16",
                dimension="Phase Prerequisites",
                severity="PASS",
                title="✅ Phase 1 無前置要求",
                detail="",
            ))
            return

        found = []
        missing = []
        for path in prereqs:
            if self.gh.file_exists(path):
                found.append(path)
            else:
                missing.append(path)

        # 去重：SRS.md 和 01-requirements/SRS.md 只需一個存在
        unique_docs = {}
        for p in prereqs:
            base = p.split("/")[-1]
            if base not in unique_docs:
                unique_docs[base] = []
            unique_docs[base].append(p)

        missing_docs = []
        for base, paths in unique_docs.items():
            if not any(self.gh.file_exists(p) for p in paths):
                missing_docs.append(base)

        if not missing_docs:
            self.result.add(Finding(
                check_id="C16",
                dimension="Phase Prerequisites",
                severity="PASS",
                title=f"✅ Phase {self.phase} 前置產出物齊全（{len(unique_docs)} 項）",
                detail=f"已確認：{', '.join(unique_docs.keys())}",
            ))
        else:
            self.result.add(Finding(
                check_id="C16",
                dimension="Phase Prerequisites",
                severity="CRITICAL",
                title=f"❌ Phase {self.phase} 前置產出物缺失",
                detail=f"v7.57 往前檢查：缺少 {', '.join(missing_docs)}",
                rule_ref="v7.57",
            ))

    # ── C17: Phase Outputs 產出驗證（v7.67 新增）──────────────
    def check_c17_phase_outputs(self):
        """C17: v7.67 — 檢查當前階段必要產出是否完成"""
        PHASE_OUTPUTS = {
            1: ["SRS.md", "01-requirements/SRS.md"],
            2: ["SAD.md", "02-architecture/SAD.md"],
            3: [".methodology/fr_mapping.json"],
            4: ["04-testing/TEST_PLAN.md"],
            5: ["05-verify/BASELINE.md"],
            6: ["06-quality/QUALITY_REPORT.md"],
            7: ["08-config/CONFIG_RECORDS.md", "08-config/requirements.lock"],
            8: [],
        }

        outputs = PHASE_OUTPUTS.get(self.phase, [])
        if not outputs:
            self.result.add(Finding(
                check_id="C17",
                dimension="Phase Outputs",
                severity="PASS",
                title=f"✅ Phase {self.phase} 無必要產出檢查",
                detail="",
            ))
            return

        # 去重：同一文件的多路徑只需一個存在
        unique_outputs = {}
        for p in outputs:
            base = p.split("/")[-1]
            if base not in unique_outputs:
                unique_outputs[base] = []
            unique_outputs[base].append(p)

        missing_outputs = []
        for base, paths in unique_outputs.items():
            if not any(self.gh.file_exists(p) for p in paths):
                missing_outputs.append(base)

        if not missing_outputs:
            self.result.add(Finding(
                check_id="C17",
                dimension="Phase Outputs",
                severity="PASS",
                title=f"✅ Phase {self.phase} 必要產出齊全（{len(unique_outputs)} 項）",
                detail=f"已確認：{', '.join(unique_outputs.keys())}",
            ))
        else:
            self.result.add(Finding(
                check_id="C17",
                dimension="Phase Outputs",
                severity="WARNING",
                title=f"⚠️ Phase {self.phase} 必要產出未完成",
                detail=f"v7.67 Post-flight：缺少 {', '.join(missing_outputs)}",
                rule_ref="v7.67",
            ))

    # ── 執行所有檢查 ──────────────────────────────────
    def run_all_checks(self) -> AuditResult:
        print(f"\
{'='*60}")
        print(f"🔍 審計 {self.gh.repo} — Phase {self.phase}: {self.spec.get('name','')}")
        print(f"{'='*60}")

        checks = [
            ("C1 交付物完整性",        self.check_c1_deliverables),
            ("C2 STAGE_PASS 憑證",     self.check_c2_stage_pass),
            ("C3 A/B Session 分離",    self.check_c3_session_separation),
            ("C4 DEVELOPMENT_LOG 品質", self.check_c4_development_log),
            ("C5 文件內容深度",         self.check_c5_content_depth),
            ("C6 Commit 時間線",        self.check_c6_commit_timeline),
            ("C7 Claims 交叉驗證",      self.check_c7_claims_crosscheck),
            ("C8 Integrity Tracker",   self.check_c8_integrity),
            ("C9 Traceability Annotation", self.check_c9_traceability_annotations),
            ("C10 Runtime Metrics",    self.check_c10_runtime_metrics),
            ("C11 Verify_Agent 記錄",  self.check_c11_verify_agent),
            ("C12 Citations HR-15",     self.check_c12_citations_quality),
            ("C13 FORBIDDEN 模式",     self.check_c13_forbidden_patterns),
            ("C14 run-phase 入口驗證",  self.check_c14_run_phase_entry),
            ("C15 artifact_verification", self.check_c15_artifact_verification),
            ("C16 Phase Prerequisites",   self.check_c16_phase_prerequisites),
            ("C17 Phase Outputs",          self.check_c17_phase_outputs),
        ]
        for name, fn in checks:
            print(f"  → {name}...", end=" ", flush=True)
            fn()
            print("done")

        self._calculate_score()
        return self.result

    def _calculate_score(self):
        """計算綜合審計分數與最終裁決"""
        findings = self.result.findings
        criticals = len([f for f in findings if f.severity == "CRITICAL"])
        warnings  = len([f for f in findings if f.severity == "WARNING"])
        passes    = len([f for f in findings if f.severity == "PASS"])

        total = criticals + warnings + passes
        if total == 0:
            info_count = len([f for f in findings if f.severity == "INFO"])
            if info_count > 0:
                self.result.score = 50
                self.result.verdict = "CONDITIONAL_PASS"
            else:
                self.result.score = 0
                self.result.verdict = "FAIL"
            return

        # 加權分數：PASS=1分, WARNING=-0.3分, CRITICAL=-1.5分（相對於通過基準）
        raw = passes - (warnings * 0.3) - (criticals * 1.5)
        self.result.score = max(0, min(100, (raw / total) * 100))

        if criticals == 0 and self.result.score >= 60:
            self.result.verdict = "PASS"
        elif criticals <= 1 and self.result.score >= 40:
            self.result.verdict = "CONDITIONAL_PASS"
        else:
            self.result.verdict = "FAIL"


# ─────────────────────────────────────────────
# 5. 報告生成器
# ─────────────────────────────────────────────

def generate_report(result: AuditResult, output_format: str = "markdown") -> str:
    verdict_icon = {"PASS": "✅", "CONDITIONAL_PASS": "⚠️", "FAIL": "❌"}.get(result.verdict, "❓")
    verdict_label = {
        "PASS": "通過",
        "CONDITIONAL_PASS": "有條件通過（需修正）",
        "FAIL": "不通過",
    }.get(result.verdict, result.verdict)

    findings_by_dim: dict[str, list[Finding]] = {}
    for f in result.findings:
        findings_by_dim.setdefault(f.dimension, []).append(f)

    criticals = result.criticals()
    warnings  = result.warnings()
    passes    = result.passes()

    lines = [
        f"# 審計報告 — Phase {result.phase}: {result.phase_name}",
        f"",
        f"> **專案**：{result.repo}  ",
        f"> **審計時間**：{result.audit_time}  ",
        f"> **方法論版本**：methodology-v2 v8.0  ",
        f"> **審計工具**：phase_auditor.py  ",
        f"",
        f"---",
        f"",
        f"## 最終裁決",
        f"",
        f"| 項目 | 數值 |",
        f"|------|------|",
        f"| 裁決 | {verdict_icon} **{verdict_label}** |",
        f"| 審計分數 | **{result.score:.1f} / 100** |",
        f"| 嚴重問題（CRITICAL） | {len(criticals)} 個 |",
        f"| 警告（WARNING） | {len(warnings)} 個 |",
        f"| 通過項目（PASS） | {len(passes)} 個 |",
        f"",
    ]

    if criticals:
        lines += [
            f"## 🔴 嚴重問題（必須修正才能進入下一 Phase）",
            f"",
        ]
        for f in criticals:
            lines.append(f"### {f.title}")
            lines.append(f"- **維度**：{f.dimension}")
            lines.append(f"- **Check ID**：{f.check_id}")
            if f.rule_ref:
                lines.append(f"- **規則依據**：{f.rule_ref} — {HARD_RULES.get(f.rule_ref, '')}")
            lines.append(f"- **詳情**：{f.detail}")
            if f.evidence:
                lines.append(f"- **證據**：{f.evidence}")
            lines.append("")

    if warnings:
        lines += [
            f"## 🟡 警告（建議修正）",
            f"",
        ]
        for f in warnings:
            lines.append(f"- {f.title}")
            if f.detail:
                lines.append(f"  - {f.detail}")
            if f.rule_ref:
                lines.append(f"  - 規則：{f.rule_ref}")
        lines.append("")

    lines += [
        f"## 各維度詳細結果",
        f"",
    ]
    for dim, dim_findings in findings_by_dim.items():
        dim_criticals = sum(1 for f in dim_findings if f.severity == "CRITICAL")
        dim_warnings  = sum(1 for f in dim_findings if f.severity == "WARNING")
        dim_icon = "🔴" if dim_criticals > 0 else ("🟡" if dim_warnings > 0 else "✅")
        lines.append(f"### {dim_icon} {dim}")
        lines.append(f"")
        for f in dim_findings:
            lines.append(f"- {f.title}")
            if f.detail and f.severity != "PASS":
                for detail_line in f.detail.splitlines():
                    lines.append(f"  > {detail_line}")
        lines.append("")

    # 修正建議
    if criticals or warnings:
        lines += [
            f"## 修正建議",
            f"",
        ]
        for i, f in enumerate(criticals, 1):
            lines.append(f"{i}. **[CRITICAL]** {f.title.removeprefix('❌ ')}")
            if f.detail and f.detail.splitlines():
                lines.append(f"   - {f.detail.splitlines()[0]}")
        for i, f in enumerate(warnings, len(criticals) + 1):
            lines.append(f"{i}. **[WARNING]** {f.title.removeprefix('⚠️ ')}")
        lines.append("")

    # 下一步
    lines += [
        f"## 下一步",
        f"",
    ]
    if result.verdict == "PASS":
        lines.append(f"✅ Phase {result.phase} 審計通過，可進入 Phase {result.phase + 1}。")
    elif result.verdict == "CONDITIONAL_PASS":
        lines.append(f"⚠️ 修正上述 WARNING 項目後，再次執行 `python phase_auditor.py --repo {result.repo} --phase {result.phase}` 重新驗證。")
    else:
        lines.append(f"❌ 修正所有 CRITICAL 問題後，重新提交 Phase {result.phase} 產物，並再次執行審計。")

    lines += [
        f"",
        f"---",
        f"*由 phase_auditor.py 自動生成 | methodology-v2 v8.0*",
    ]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 6. 主程式入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="methodology-v2 Phase Auditor — 基於 GitHub 產物的獨立審計工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
初始化必要資訊（project_context）
──────────────────────────────────
  必填：
    --repo    GitHub repo，格式為 owner/repo
              例：johnnylugm-tech/tts-kokoro-v613
    --phase   審計的 Phase 編號（1-8）

  選填（有合理預設值）：
    --branch  目標分支（預設：main）
    --output  輸出格式 markdown|json（預設：markdown）
    --save    將報告儲存到指定檔案

  無需提供（工具自動偵測）：
    - methodology 版本（從 STAGE_PASS 或 DEVELOPMENT_LOG 自動偵測）
    - Phase 規格（內建 SKILL.md v8.0 規則庫）
    - 文件路徑（支援多種命名慣例自動解析）

使用範例：
    python phase_auditor.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 1
    python phase_auditor.py --repo OWNER/REPO --phase 3 --output json
    python phase_auditor.py --repo OWNER/REPO --phase 1 --save audit_phase1.md
        """,
    )
    parser.add_argument("--repo", required=True,
                        help="GitHub repo (owner/repo)")
    parser.add_argument("--phase", type=int, required=True, choices=range(1, 9),
                        help="審計的 Phase 編號 (1-8)")
    parser.add_argument("--branch", default="main",
                        help="目標分支（預設：main）")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown",
                        help="輸出格式")
    parser.add_argument("--save", metavar="FILE",
                        help="將報告存到檔案")
    args = parser.parse_args()

    if args.phase not in PHASE_SPEC:
        print(f"❌ Phase {args.phase} 尚未定義，支援範圍：1-8", file=sys.stderr)
        sys.exit(1)

    # 初始化 GitHub 存取層
    fetcher = GitHubFetcher(repo=args.repo, branch=args.branch)

    # 確認 repo 可存取
    repo_info = fetcher.get_repo_info()
    if not repo_info:
        print(f"❌ 無法存取 repo：{args.repo}（請確認 gh auth status）", file=sys.stderr)
        sys.exit(1)

    # 執行審計
    auditor = PhaseAuditor(fetcher=fetcher, phase=args.phase)
    result = auditor.run_all_checks()

    # 輸出報告
    if args.output == "json":
        output = json.dumps({
            "repo": result.repo,
            "phase": result.phase,
            "phase_name": result.phase_name,
            "audit_time": result.audit_time,
            "score": result.score,
            "verdict": result.verdict,
            "findings": [
                {
                    "check_id": f.check_id,
                    "dimension": f.dimension,
                    "severity": f.severity,
                    "title": f.title,
                    "detail": f.detail,
                    "rule_ref": f.rule_ref,
                }
                for f in result.findings
            ],
        }, ensure_ascii=False, indent=2)
    else:
        output = generate_report(result)

    if args.save:
        with open(args.save, "w", encoding="utf-8") as fp:
            fp.write(output)
        print(f"\
📄 報告已儲存至：{args.save}")
    else:
        print("\
" + output)

    # Exit code
    exit_codes = {"PASS": 0, "CONDITIONAL_PASS": 1, "FAIL": 2}
    sys.exit(exit_codes.get(result.verdict, 2))


if __name__ == "__main__":
    main()
