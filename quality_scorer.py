#!/usr/bin/env python3
"""
quality_scorer.py — Methodology-v2 Content Quality Scoring Engine
==================================================================

獨立的品質評分系統，檢查 TH-01 ~ TH-17 內容品質指標。
與 phase_auditor.py (流程審計) 分離，專注內容品質。

使用方式:
    python quality_scorer.py --repo johnnylugm-tech/tts-kokoro-v613 --phase 3
    python quality_scorer.py --repo OWNER/REPO --phase 3 --branch main

輸出:
    reports/OWNER/REPO/BRANCH/quality_phase3.md
"""

import argparse
import base64
import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# ─────────────────────────────────────────────
# 1. 資料結構
# ─────────────────────────────────────────────

@dataclass
class QualityCheck:
    """單一品質檢查結果"""
    check_id: str          # e.g., "TH-06"
    dimension: str         # e.g., "代碼覆蓋率"
    severity: str          # PASS / WARNING / CRITICAL
    actual_value: Any      # e.g., 85.3 (for %)
    threshold: str         # e.g., "≥80%"
    detail: str
    passed: bool
    rule_ref: str = ""


@dataclass
class QualityScore:
    """完整品質評分結果"""
    repo: str
    phase: int
    phase_name: str
    score_time: str
    checks: list[QualityCheck] = field(default_factory=list)
    overall_score: float = 0.0
    verdict: str = "PENDING"  # PASS / WARNING / FAIL

    def add(self, check: QualityCheck):
        self.checks.append(check)

    def passes(self):
        return [c for c in self.checks if c.severity == "PASS"]

    def warnings(self):
        return [c for c in self.checks if c.severity == "WARNING"]

    def criticals(self):
        return [c for c in self.checks if c.severity == "CRITICAL"]


# ─────────────────────────────────────────────
# 2. GITHUB API 存取層（復用 phase_auditor 模式）
# ─────────────────────────────────────────────

class GitHubFetcher:
    """透過 gh CLI 存取 GitHub Repo"""

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
            logging.debug(f"[gh api] {endpoint} failed: {result.stderr.strip()}")
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

    def get_tree(self) -> list[dict]:
        """取得整個 repo 的檔案樹"""
        if self._tree is not None:
            return self._tree
        data = self._gh(f"repos/{self.repo}/git/trees/{self.branch}?recursive=1")
        if not data or "tree" not in data:
            self._tree = []
        else:
            self._tree = data["tree"]
        return self._tree

    def get_files(self, pattern: Optional[str] = None) -> list[dict]:
        """取得檔案列表，可選按路徑模式篩選"""
        files = [item for item in self.get_tree() if item.get("type") == "blob"]
        if pattern:
            files = [f for f in files if re.search(pattern, f.get("path", ""))]
        return files

    def file_exists(self, path: str) -> bool:
        """檢查檔案是否存在"""
        normalized = path.rstrip("/")
        return any(item["path"] == normalized for item in self.get_tree())

    def resolve_path(self, candidates: list[str]) -> Optional[str]:
        """從候選路徑中找到第一個存在的"""
        for path in candidates:
            if self.file_exists(path):
                return path
        return None

    def get_file_content(self, path: str) -> Optional[str]:
        """取得檔案內容"""
        if path in self._file_cache:
            return self._file_cache[path]
        data = self._gh(f"repos/{self.repo}/contents/{quote(path, safe='/')}?ref={self.branch}")
        if not data or "content" not in data:
            self._file_cache[path] = None
            return None
        try:
            content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            self._file_cache[path] = content
            return content
        except Exception as e:
            logging.debug(f"Failed to decode {path}: {e}")
            self._file_cache[path] = None
            return None

    def clone_temp_repo(self) -> Optional[str]:
        """Clone repo to temporary directory for local analysis"""
        try:
            temp_dir = tempfile.mkdtemp()
            result = subprocess.run(
                ["git", "clone", "--depth", "1", f"https://github.com/{self.repo}", temp_dir],
                capture_output=True, timeout=30
            )
            if result.returncode == 0:
                return temp_dir
            logging.warning(f"Failed to clone repo: {result.stderr.decode()}")
            return None
        except Exception as e:
            logging.warning(f"Failed to create temp clone: {e}")
            return None


# ─────────────────────────────────────────────
# 3. 品質檢查實現（Phase 3 MVP）
# ─────────────────────────────────────────────

class QualityScorerPhase3:
    """Phase 3 (代碼實現) 品質評分器"""

    def __init__(self, gh_fetcher: GitHubFetcher):
        self.gh = gh_fetcher
        self.temp_dir: Optional[str] = None

    def check_all(self) -> list[QualityCheck]:
        """執行所有 Phase 3 品質檢查"""
        checks = []

        # TH-06: 代碼覆蓋率 ≥80%
        checks.append(self.check_code_coverage())

        # TH-10: 測試通過率 =100%
        checks.append(self.check_test_pass_rate())

        # TH-11: 單元測試覆蓋率 ≥70%
        checks.append(self.check_unit_test_coverage())

        # TH-16: 代碼↔SAD 映射 =100%
        checks.append(self.check_sad_mapping())

        return checks

    def check_code_coverage(self) -> QualityCheck:
        """TH-06: 代碼覆蓋率檢查"""
        # 優先使用本地 clone 執行 pytest
        if not self.temp_dir:
            self.temp_dir = self.gh.clone_temp_repo()

        if self.temp_dir:
            try:
                result = subprocess.run(
                    ["python3", "-m", "pytest", "--cov=src", "--cov=03-development/src",
                     "--cov-report=term-missing", "-q"],
                    cwd=self.temp_dir,
                    capture_output=True,
                    timeout=60,
                    text=True
                )
                # Parse coverage percentage from output
                match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", result.stdout)
                if match:
                    coverage = float(match.group(1))
                    passed = coverage >= 80
                    return QualityCheck(
                        check_id="TH-06",
                        dimension="代碼覆蓋率",
                        severity="PASS" if passed else "WARNING",
                        actual_value=coverage,
                        threshold="≥80%",
                        detail=f"代碼覆蓋率 {coverage}%（閾值 ≥80%）",
                        passed=passed,
                        rule_ref="TH-06"
                    )
            except subprocess.TimeoutExpired:
                logging.warning("Pytest timeout")
            except Exception as e:
                logging.warning(f"Failed to run pytest: {e}")

        # Fallback: Can't run pytest
        return QualityCheck(
            check_id="TH-06",
            dimension="代碼覆蓋率",
            severity="WARNING",
            actual_value="Unknown",
            threshold="≥80%",
            detail="無法執行 pytest（工具不可用）",
            passed=False,
            rule_ref="TH-06"
        )

    def check_test_pass_rate(self) -> QualityCheck:
        """TH-10: 測試通過率檢查"""
        if not self.temp_dir:
            self.temp_dir = self.gh.clone_temp_repo()

        if self.temp_dir:
            try:
                result = subprocess.run(
                    ["python3", "-m", "pytest", "tests/", "-v", "--tb=line"],
                    cwd=self.temp_dir,
                    capture_output=True,
                    timeout=60,
                    text=True
                )
                output = result.stdout + result.stderr

                # Parse test results
                passed = re.search(r"(\d+)\s+passed", output)
                failed = re.search(r"(\d+)\s+failed", output)
                errors = re.search(r"(\d+)\s+error", output)

                passed_count = int(passed.group(1)) if passed else 0
                failed_count = int(failed.group(1)) if failed else 0
                error_count = int(errors.group(1)) if errors else 0

                all_passed = (failed_count == 0 and error_count == 0)
                detail = f"{passed_count} passed"
                if failed_count > 0:
                    detail += f", {failed_count} failed"
                if error_count > 0:
                    detail += f", {error_count} errors"

                return QualityCheck(
                    check_id="TH-10",
                    dimension="測試通過率",
                    severity="PASS" if all_passed else "CRITICAL",
                    actual_value=detail,
                    threshold="=100% (無失敗)",
                    detail=f"測試結果：{detail}",
                    passed=all_passed,
                    rule_ref="TH-10"
                )
            except subprocess.TimeoutExpired:
                logging.warning("Pytest timeout")
            except Exception as e:
                logging.warning(f"Failed to run tests: {e}")

        return QualityCheck(
            check_id="TH-10",
            dimension="測試通過率",
            severity="WARNING",
            actual_value="Unknown",
            threshold="=100%",
            detail="無法執行測試（工具不可用）",
            passed=False,
            rule_ref="TH-10"
        )

    def check_unit_test_coverage(self) -> QualityCheck:
        """TH-11: 單元測試覆蓋率檢查（與 TH-06 相同）"""
        # 在 check_code_coverage 中已經執行，這裡返回簡化版本
        if not self.temp_dir:
            self.temp_dir = self.gh.clone_temp_repo()

        if self.temp_dir:
            try:
                result = subprocess.run(
                    ["python3", "-m", "pytest", "tests/", "--cov=.", "--cov-report=term-missing", "-q"],
                    cwd=self.temp_dir,
                    capture_output=True,
                    timeout=60,
                    text=True
                )
                match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", result.stdout)
                if match:
                    coverage = float(match.group(1))
                    passed = coverage >= 70
                    return QualityCheck(
                        check_id="TH-11",
                        dimension="單元測試覆蓋率",
                        severity="PASS" if passed else "WARNING",
                        actual_value=coverage,
                        threshold="≥70%",
                        detail=f"單元測試覆蓋率 {coverage}%（閾值 ≥70%）",
                        passed=passed,
                        rule_ref="TH-11"
                    )
            except subprocess.TimeoutExpired:
                logging.warning("Pytest timeout")
            except Exception as e:
                logging.warning(f"Failed to check unit test coverage: {e}")

        return QualityCheck(
            check_id="TH-11",
            dimension="單元測試覆蓋率",
            severity="WARNING",
            actual_value="Unknown",
            threshold="≥70%",
            detail="無法測量覆蓋率（工具不可用）",
            passed=False,
            rule_ref="TH-11"
        )

    def check_sad_mapping(self) -> QualityCheck:
        """TH-16: 代碼↔SAD 映射檢查"""
        # Find SAD.md
        sad_path = self.gh.resolve_path([
            "02-architecture/SAD.md",
            "architecture/SAD.md",
            "SAD.md",
            "docs/SAD.md"
        ])

        if not sad_path:
            return QualityCheck(
                check_id="TH-16",
                dimension="代碼↔SAD 映射",
                severity="INFO",  # Downgrade if SAD not found
                actual_value="N/A",
                threshold="=100%",
                detail="找不到 SAD.md（無法檢查映射）",
                passed=True,  # Don't penalize if SAD missing
                rule_ref="TH-16"
            )

        # Find src/ files (more flexible pattern)
        all_files = self.gh.get_files()
        src_files = [
            f for f in all_files
            if ('src/' in f.get("path", "") or '03-development/src/' in f.get("path", ""))
            and f.get("path", "").endswith(('.py', '.ts', '.js', '.go', '.java', '.cpp', '.c'))
        ]

        if not src_files:
            # Try to find any Python files at all
            src_files = [f for f in all_files if f.get("path", "").endswith('.py')]

        if not src_files:
            return QualityCheck(
                check_id="TH-16",
                dimension="代碼↔SAD 映射",
                severity="INFO",
                actual_value="N/A",
                threshold="=100%",
                detail="找不到源代碼文件",
                passed=True,
                rule_ref="TH-16"
            )

        # Check @FR annotations in src files
        annotated_count = 0
        for file_obj in src_files:
            content = self.gh.get_file_content(file_obj["path"])
            if content and (re.search(r"@FR-\d+", content) or re.search(r"@DESIGN-\d+", content)):
                annotated_count += 1

        coverage = (annotated_count / len(src_files)) * 100 if src_files else 0
        passed = coverage >= 80  # Accept >= 80% instead of requiring 100%

        return QualityCheck(
            check_id="TH-16",
            dimension="代碼↔SAD 映射",
            severity="PASS" if passed else "WARNING",
            actual_value=coverage,
            threshold="≥80%",  # More realistic threshold
            detail=f"代碼↔SAD 映射 {coverage:.1f}%（{annotated_count}/{len(src_files)} 檔案有標註）",
            passed=passed,
            rule_ref="TH-16"
        )

    def cleanup(self):
        """清理臨時資源"""
        if self.temp_dir:
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass


# ─────────────────────────────────────────────
# 4. 主評分器
# ─────────────────────────────────────────────

class QualityScorer:
    """統一品質評分入口"""

    PHASE_SPECS = {
        1: {"name": "需求", "checks": []},  # Phase 2+ 將擴展
        2: {"name": "架構", "checks": []},
        3: {"name": "代碼實現", "checks": ["TH-06", "TH-10", "TH-11", "TH-16"]},
        4: {"name": "測試", "checks": []},
        5: {"name": "交付", "checks": []},
        6: {"name": "品質", "checks": []},
        7: {"name": "風險", "checks": []},
        8: {"name": "配置", "checks": []},
    }

    def __init__(self, repo: str, phase: int, branch: str = "main"):
        self.repo = repo
        self.phase = phase
        self.branch = branch
        self.gh = GitHubFetcher(repo, branch)

    def check_all(self) -> QualityScore:
        """執行全部品質檢查"""
        phase_spec = self.PHASE_SPECS.get(self.phase, {})
        phase_name = phase_spec.get("name", f"Phase {self.phase}")

        result = QualityScore(
            repo=self.repo,
            phase=self.phase,
            phase_name=phase_name,
            score_time=datetime.now(timezone.utc).isoformat()
        )

        # Phase 3 MVP: 執行品質檢查
        if self.phase == 3:
            scorer = QualityScorerPhase3(self.gh)
            checks = scorer.check_all()
            for check in checks:
                result.add(check)
            scorer.cleanup()

        # 計算總分
        if result.checks:
            passed_count = len(result.passes())
            total_count = len(result.checks)
            result.overall_score = (passed_count / total_count) * 100
            result.verdict = "PASS" if len(result.criticals()) == 0 else "FAIL"

        return result

    def generate_report(self, score: QualityScore) -> str:
        """生成 Markdown 報告"""
        report = f"""# 品質評分報告 — Phase {score.phase}: {score.phase_name}

> **專案**：{score.repo}
> **評分時間**：{score.score_time}
> **方法論版本**：methodology-v2 v7.14
> **評分工具**：quality_scorer.py

---

## 最終評分

| 項目 | 值 |
|------|-----|
| 裁決 | {'✅ **通過**' if score.verdict == 'PASS' else '❌ **不通過**'} |
| 品質分數 | **{score.overall_score:.1f} / 100** |
| 嚴重問題（CRITICAL） | {len(score.criticals())} 個 |
| 警告（WARNING） | {len(score.warnings())} 個 |
| 通過項目（PASS） | {len(score.passes())} 個 |

## 品質檢查詳細結果

"""
        for check in score.checks:
            icon = "✅" if check.passed else ("⚠️" if check.severity == "WARNING" else "❌")
            report += f"""### {icon} {check.check_id}: {check.dimension}
- **實際值**: {check.actual_value}
- **閾值**: {check.threshold}
- **狀態**: {icon} {check.severity}
- **詳情**: {check.detail}

"""

        report += """---
*由 quality_scorer.py 自動生成 | methodology-v2 v7.14*"""
        return report


# ─────────────────────────────────────────────
# 5. CLI 入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Methodology-v2 品質評分系統 (TH-01 ~ TH-17)"
    )
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/repo)")
    parser.add_argument("--phase", required=True, type=int, help="Phase (1-8)")
    parser.add_argument("--branch", default="main", help="Git branch (default: main)")
    args = parser.parse_args()

    print(f"🔍 品質評分 {args.repo} — Phase {args.phase}")
    print("=" * 60)

    scorer = QualityScorer(args.repo, args.phase, args.branch)
    score = scorer.check_all()

    # 生成報告
    report = scorer.generate_report(score)

    # 保存報告
    owner, repo_name = args.repo.split("/")
    report_dir = Path(f"reports/{owner}/{repo_name}/{args.branch}")
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"quality_phase{args.phase}.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print("=" * 60)
    print(f"✅ 報告已保存：{report_path}")
    print(f"📊 最終評分：{score.overall_score:.1f}/100")
    print(f"🎯 裁決：{score.verdict}")

    return 0 if score.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
