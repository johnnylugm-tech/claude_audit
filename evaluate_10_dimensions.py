#!/usr/bin/env python3
"""
10 Dimension Quality Evaluator
============================
執行所有 10 個品質維度的評估
"""

import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List

# ============================================================================
# Tool Layer Implementations
# ============================================================================

class ToolBasedChecker:
    """Tool 層 - 結構化檢查"""
    
    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path)
    
    def check_linting(self) -> float:
        """1. Linting - 使用 Constitution"""
        # 嘗試載入 methodology-v2 Constitution
        try:
            import sys
            sys.path.insert(0, "/workspace/methodology-v2")
            from constitution.constitution_runner import ConstitutionRunner
            runner = ConstitutionRunner(str(self.repo_path))
            result = runner.run()
            return result.get("overall_score", 50)
        except:
            pass
        
        # Fallback: 簡單的語法檢查
        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile"] + list(self.repo_path.glob("*.py")),
                capture_output=True, timeout=30
            )
            return 100 if result.returncode == 0 else 50
        except:
            return 50
    
    def check_type_safety(self) -> float:
        """2. Type Safety"""
        # 檢查類型註釋覆蓋率
        py_files = list(self.repo_path.glob("**/*.py"))
        if not py_files:
            return 0
        
        total_lines = 0
        typed_lines = 0
        
        for f in py_files:
            try:
                content = f.read_text()
                lines = content.split('\n')
                total_lines += len(lines)
                # 簡單檢查：是否有類型註釋
                typed_lines += sum(1 for l in lines if ': ' in l and any(t in l for t in ['str', 'int', 'bool', 'list', 'dict', 'Optional', 'Union']))
            except:
                pass
        
        return (typed_lines / max(total_lines, 1)) * 100
    
    def check_test_coverage(self) -> float:
        """3. Test Coverage - 計算 test_auditor.py 中的測試數量"""
        # 使用相對路徑確保正確讀取
        test_file = Path("/workspace/claude_audit/test_auditor.py")
        
        if not test_file.exists():
            # 嘗試專案路徑
            test_file = self.repo_path / "test_auditor.py"
        
        if not test_file.exists() or not test_file.is_file():
            return 0
        
        try:
            content = test_file.read_text(encoding="utf-8")
            test_count = content.count('def test_')
            return min(test_count * 10, 100)
        except Exception as e:
            print(f"Error reading test file: {e}")
            return 0
    
    def check_security(self) -> float:
        """4. Security"""
        # 檢查常見安全問題
        py_files = list(self.repo_path.glob("*.py"))
        
        issues = 0
        for f in py_files:
            try:
                content = f.read_text()
                # 簡單檢查
                if 'password' in content.lower() and '=' in content:
                    if 'os.environ' not in content and 'env' not in content:
                        issues += 1
                if 'eval(' in content:
                    issues += 1
                if 'exec(' in content:
                    issues += 1
            except:
                pass
        
        return max(100 - issues * 20, 0)
    
    def check_performance(self) -> float:
        """5. Performance"""
        # 測量載入時間
        try:
            start = time.time()
            for f in self.repo_path.glob("*.py"):
                if f.name not in ["test_*.py", "*_test.py"]:
                    subprocess.run(["python3", str(f), "--help"], 
                                  capture_output=True, timeout=5)
            elapsed = time.time() - start
            return max(100 - elapsed * 10, 50)
        except:
            return 50
    
    def check_architecture(self) -> float:
        """6. Architecture"""
        # 檢查模組數量和分離
        py_files = list(self.repo_path.glob("*.py"))
        if not py_files:
            return 0
        
        # 計算平均檔案大小
        total_size = sum(f.stat().st_size for f in py_files)
        avg_size = total_size / len(py_files)
        
        # 檔案越小分數越高（表示有分離）
        if avg_size > 10000:  # > 10KB
            return 30
        elif avg_size > 5000:
            return 60
        else:
            return 90
    
    def check_readability(self) -> float:
        """7. Readability"""
        # 檢查函數長度和命名
        py_files = list(self.repo_path.glob("*.py"))
        
        long_functions = 0
        for f in py_files:
            try:
                content = f.read_text()
                for func in content.split('def '):
                    lines = func.split('\n')
                    if len(lines) > 50:  # 函數太長
                        long_functions += 1
            except:
                pass
        
        return max(100 - long_functions * 15, 30)
    
    def check_error_handling(self) -> float:
        """8. Error Handling"""
        py_files = list(self.repo_path.glob("*.py"))
        
        error_handling = 0
        for f in py_files:
            try:
                content = f.read_text()
                if 'except' in content:
                    error_handling += 1
                if 'try:' in content:
                    error_handling += 1
                if 'raise' in content:
                    error_handling += 1
            except:
                pass
        
        return min(error_handling * 15, 100)
    
    def check_documentation(self) -> float:
        """9. Documentation"""
        py_files = list(self.repo_path.glob("*.py"))
        
        doc_count = 0
        for f in py_files:
            try:
                content = f.read_text()
                if '"""' in content or "'''" in content:
                    doc_count += 1
                if f.read_text().startswith('#'):
                    doc_count += 1
            except:
                pass
        
        return min(doc_count * 20, 100)
    
    def check_claims(self) -> float:
        """10. Claims Verification (HR-09)"""
        # 檢查是否有 claims 追蹤機制
        files = list(self.repo_path.glob("*claim*")) + list(self.repo_path.glob("* Claim*"))
        
        if files:
            return 80
        
        # 檢查是否有TODO或 FIXME
        py_files = list(self.repo_path.glob("*.py"))
        todo_count = 0
        for f in py_files:
            try:
                content = f.read_text()
                todo_count += content.count('TODO') + content.count('FIXME')
            except:
                pass
        
        return min(todo_count * 10, 60)


# ============================================================================
# LLM Layer - Mock（實際實現時會呼叫真實 LLM）
# ============================================================================

class LLMAnalyzer:
    """LLM 層 - 推理和建議"""
    
    def analyze_dimension(self, dimension: str, tool_score: float) -> Dict:
        """分析維度並給出建議"""
        
        descriptions = {
            "Linting": "代碼風格和格式一致性檢查",
            "Type Safety": "類型註釋和類型安全",
            "Test Coverage": "測試覆蓋率和測試品質",
            "Security": "安全漏洞和敏感資訊處理",
            "Performance": "執行效率和資源使用",
            "Architecture": "模組結構和單一職責",
            "Readability": "代碼可讀性和命名規範",
            "Error Handling": "異常處理和錯誤恢復",
            "Documentation": "文檔說明和註釋",
            "Claims Verification": "承諾追蹤和驗證"
        }
        
        suggestions = {
            "Linting": "使用 black 自動格式化，遵循 PEP 8",
            "Type Safety": "添加函數簽名類型註釋和返回類型",
            "Test Coverage": "增加單元測試覆蓋關鍵函數",
            "Security": "使用環境變數管理敏感資訊",
            "Performance": "考慮使用快取和非同步處理",
            "Architecture": "將大型模組拆分為多個小模組",
            "Readability": "縮短函數長度，使用清晰命名",
            "Error Handling": "添加具體的異常處理和日誌",
            "Documentation": "為模組和函數添加 docstring",
            "Claims Verification": "建立 claim 追蹤表，定期驗證"
        }
        
        return {
            "description": descriptions.get(dimension, dimension),
            "suggestion": suggestions.get(dimension, "需要優化"),
            "priority": "HIGH" if tool_score < 50 else "MEDIUM" if tool_score < 70 else "LOW"
        }


# ============================================================================
# Main Evaluator
# ============================================================================

def run_10_dimension_evaluation(repo_path: str = ".") -> Dict:
    """執行 10 維度評估"""
    
    print("=" * 70)
    print("10 Dimension Quality Evaluation")
    print("=" * 70)
    
    tool_checker = ToolBasedChecker(repo_path)
    llm_analyzer = LLMAnalyzer()
    
    # 維度定義
    dimensions = [
        ("1", "Linting", tool_checker.check_linting),
        ("2", "Type Safety", tool_checker.check_type_safety),
        ("3", "Test Coverage", tool_checker.check_test_coverage),
        ("4", "Security", tool_checker.check_security),
        ("5", "Performance", tool_checker.check_performance),
        ("6", "Architecture", tool_checker.check_architecture),
        ("7", "Readability", tool_checker.check_readability),
        ("8", "Error Handling", tool_checker.check_error_handling),
        ("9", "Documentation", tool_checker.check_documentation),
        ("10", "Claims Verification", tool_checker.check_claims),
    ]
    
    results = []
    weights = {
        "Linting": 0.10, "Type Safety": 0.15, "Test Coverage": 0.20,
        "Security": 0.15, "Performance": 0.10, "Architecture": 0.10,
        "Readability": 0.10, "Error Handling": 0.05, "Documentation": 0.05,
        "Claims Verification": 0.05
    }
    
    print("\n📊 Executing 10 Dimensions...\n")
    
    weighted_sum = 0
    
    for num, name, checker in dimensions:
        try:
            score = checker()
        except Exception as e:
            score = 0
            print(f"  ⚠️ Error: {e}")
        
        # LLM 分析
        llm_analysis = llm_analyzer.analyze_dimension(name, score)
        
        results.append({
            "num": num,
            "dimension": name,
            "tool_score": score,
            "weight": weights.get(name, 0),
            "llm_analysis": llm_analysis
        })
        
        weighted_sum += score * weights.get(name, 0)
        
        # 顯示結果
        bar_len = int(score / 5)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        
        status = "🔴" if score < 50 else "🟡" if score < 70 else "🟢"
        
        print(f"{num}. {name:20s} | {bar} | {score:5.1f} {status}")
        print(f"   Tool: 自動檢查 → {score:.1f}")
        print(f"   LLM:  {llm_analysis['priority']}優先 - {llm_analysis['suggestion'][:50]}...")
        print()
    
    # 總分
    print("=" * 70)
    print(f"📈 OVERALL SCORE (Weighted): {weighted_sum:.1f}/100")
    print("=" * 70)
    
    return {
        "dimensions": results,
        "overall": weighted_sum
    }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="10 Dimension Quality Evaluator")
    parser.add_argument("--repo", default=".", help="Repository path")
    
    args = parser.parse_args()
    run_10_dimension_evaluation(args.repo)