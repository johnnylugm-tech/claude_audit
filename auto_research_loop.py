#!/usr/bin/env python3
"""
AutoResearch Quality - Hybrid Loop
Tool 執行評估 → LLM 推理改善 → Dashboard 即時監控
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# ============================================================================
# Tool Layer - 使用 methodology-v2
# ============================================================================

import sys
sys.path.insert(0, "/workspace/methodology-v2")


class ToolBasedEvaluator:
    """Tool 層 - 結構化數據收集（使用 methodology-v2）"""
    
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)
        
        # 嘗試載入 methodology-v2 模組
        self._load_methodology_modules()
    
    def _load_methodology_modules(self):
        """載入 methodology-v2 模組"""
        try:
            from auto_quality_gate import AutoQualityGate
            self.quality_gate = AutoQualityGate()
        except ImportError:
            self.quality_gate = None
            print("⚠️ AutoQualityGate not available, using fallback")
        
        try:
            from constitution.constitution_runner import ConstitutionRunner
            self.constitution = ConstitutionRunner(str(self.repo_path))
        except ImportError:
            self.constitution = None
    
    def run_constitution_check(self) -> Dict:
        """執行 Constitution 規則檢查"""
        if self.constitution:
            try:
                result = self.constitution.run()
                return {
                    "passed": result.get("passed_checks", []),
                    "failed": result.get("failed_checks", []),
                    "score": result.get("overall_score", 0),
                }
            except Exception as e:
                return {"score": 0, "error": str(e)}
        return {"score": 50, "error": "Constitution not available"}
    
    def run_quality_gate(self) -> Dict:
        """執行 Quality Gate 評估"""
        if self.quality_gate:
            try:
                result = self.quality_gate.evaluate(str(self.repo_path))
                return {
                    "overall": result.get("overall_score", 0),
                    "dimensions": result.get("dimension_scores", {}),
                    "issues": result.get("issues", [])
                }
            except Exception as e:
                return {"overall": 0, "error": str(e)}
        return {"overall": 50, "error": "QualityGate not available"}
    
    def evaluate_all_tools(self) -> Dict:
        """執行所有 Tool 評估"""
        print("\n🔧 Tool: Running evaluations...")
        
        results = {
            "constitution": self.run_constitution_check(),
            "quality_gate": self.run_quality_gate(),
        }
        
        # 計算綜合分數
        scores = {
            "constitution": results["constitution"].get("score", 50),
            "quality_gate": results["quality_gate"].get("overall", 50),
        }
        
        results["tool_overall"] = sum(scores.values()) / len(scores)
        
        print(f"  Constitution: {scores['constitution']:.1f}")
        print(f"  Quality Gate: {scores['quality_gate']:.1f}")
        print(f"  → Overall: {results['tool_overall']:.1f}")
        
        return results


# ============================================================================
# LLM Layer - 推理和決策
# ============================================================================

class LLMBasedAnalyzer:
    """LLM 層 - 推理和決策"""
    
    def __init__(self, model: str = "claude"):
        self.model = model
    
    def prioritize_dimensions(self, tool_results: Dict) -> List[str]:
        """根據 Tool 結果優先排序維度"""
        dimension_scores = tool_results.get("quality_gate", {}).get("dimensions", {})
        
        if not dimension_scores:
            # Fallback: 使用默認優先級
            return ["test_coverage", "type_safety", "error_handling", "security", "documentation"]
        
        # 按分數排序，分數越低越需要關注
        prioritized = sorted(
            dimension_scores.items(),
            key=lambda x: x[1]
        )
        
        return [d[0] for d in prioritized]
    
    def analyze_root_cause(self, dimension: str, tool_data: Dict) -> str:
        """分析維度問題的根本原因"""
        # 模擬 LLM 推理
        root_causes = {
            "test_coverage": "缺少測試文件和測試案例設計",
            "type_safety": "缺少類型註釋和返回類型定義",
            "error_handling": "缺少異常處理和錯誤日誌記錄",
            "security": "可能存在硬編碼credentials或權限控制問題",
            "documentation": "缺少模組和函數文檔說明",
            "readability": "函數過長或命名不一致",
            "architecture": "模組職責過多，缺少單一職責分離"
        }
        
        return root_causes.get(dimension, f"需要優化 {dimension}")
    
    def generate_improvements(self, dimension: str) -> List[Dict]:
        """生成改善方案"""
        improvements = {
            "test_coverage": [
                {"type": "generate_tests", "target": "test_auditor.py", "action": "Add unit tests"}
            ],
            "type_safety": [
                {"type": "add_type_hints", "target": "phase_auditor.py", "action": "Add type annotations"}
            ],
            "error_handling": [
                {"type": "add_try_except", "target": "phase_auditor.py", "action": "Wrap with try-except"}
            ],
            "security": [
                {"type": "remove_secrets", "target": "*.py", "action": "Replace hardcoded credentials"}
            ],
            "documentation": [
                {"type": "add_docstring", "target": "phase_auditor.py", "action": "Add docstrings"}
            ]
        }
        
        return improvements.get(dimension, [{"type": "review", "target": "*.py", "action": "Code review"}])
    
    def make_decision(self, before_score: float, after_score: float) -> str:
        """做出保留或還原的決策"""
        if after_score > before_score:
            return "KEEP"
        elif after_score < before_score:
            return "REVERT"
        return "KEEP"


# ============================================================================
# Dashboard Integration
# ============================================================================

class DashboardIntegrator:
    """Dashboard 整合器"""
    
    def __init__(self, data_file: str = "quality_data.json"):
        self.data_file = data_file
    
    def update_debt_trend(self, iteration: int, score: float):
        """更新技術債趨勢"""
        self._update_json("iterations", {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "debt_score": 100 - score  # 轉換為技術債（分數越高=技術債越低）
        })
    
    def update_hotspots(self, module_data: Dict):
        """更新熱點圖"""
        for module, data in module_data.items():
            self._update_json("modules", {
                "name": module,
                "issues": data.get("issues", 0),
                "complexity": data.get("complexity", 0),
                "debt": data.get("debt", 0)
            })
    
    def add_evolution(self, iteration: int, before: str, after: str, category: str, description: str):
        """記錄進化"""
        self._update_json("evolutions", {
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "before": before,
            "after": after,
            "category": category,
            "description": description
        })
    
    def _update_json(self, key: str, item: Dict):
        """更新 JSON 資料"""
        data = {"iterations": [], "modules": {}, "evolutions": []}
        
        if Path(self.data_file).exists():
            with open(self.data_file, 'r') as f:
                data = json.load(f)
        
        if key == "iterations":
            data.setdefault("iterations", []).append(item)
        elif key == "modules":
            data.setdefault("modules", {})[item["name"]] = {
                "issues": item.get("issues", 0),
                "complexity": item.get("complexity", 0),
                "debt": item.get("debt", 0)
            }
        elif key == "evolutions":
            data.setdefault("evolutions", []).append(item)
        
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def generate_report(self) -> str:
        """生成 Dashboard 報告"""
        # 使用本地 Dashboard，避免與 methodology-v2 衝突
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "local_dashboard", 
            Path(__file__).parent / "dashboard.py"
        )
        dashboard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dashboard_module)
        
        dashboard = dashboard_module.QualityDashboard(self.data_file)
        return dashboard.run_full_dashboard()


# ============================================================================
# AutoResearch Loop（完整版）
# ============================================================================

class AutoResearchLoop:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.tool_evaluator = ToolBasedEvaluator(repo_path)
        self.llm_analyzer = LLMBasedAnalyzer()
        self.dashboard = DashboardIntegrator()
        
        self.max_iterations = 20
        self.target_score = 80
        
        # 記錄改善歷史（用於 Evolution Report）
        self.improvement_history = []
    
    def run(self):
        """執行完整的 AutoResearch Loop"""
        
        print("=" * 60)
        print("AutoResearch Quality Loop - claude_audit")
        print("=" * 60)
        
        # Step 1: 基線 Tool 評估
        print("\n📊 STEP 1: Baseline Evaluation")
        baseline = self.tool_evaluator.evaluate_all_tools()
        current_score = baseline.get("tool_overall", 0)
        
        print(f"  Baseline Score: {current_score}")
        
        # 更新 Dashboard
        self.dashboard.update_debt_trend(0, current_score)
        
        best_score = current_score
        iteration = 0
        
        # Step 2: 迭代改善
        while iteration < self.max_iterations and current_score < self.target_score:
            iteration += 1
            print(f"\n{'='*60}")
            print(f"ITERATION {iteration}/{self.max_iterations}")
            print(f"{'='*60}")
            
            # LLM: 優先排序
            print("\n🤖 LLM: Prioritizing dimensions...")
            prioritized = self.llm_analyzer.prioritize_dimensions(baseline)
            weak_dim = prioritized[0] if prioritized else "general"
            print(f"  Focus: {weak_dim}")
            
            # LLM: 分析根因
            print(f"\n🤖 LLM: Analyzing root cause...")
            root_cause = self.llm_analyzer.analyze_root_cause(weak_dim, baseline)
            print(f"  → {root_cause}")
            
            # LLM: 生成改善方案
            print(f"\n🤖 LLM: Generating improvements...")
            improvements = self.llm_analyzer.generate_improvements(weak_dim)
            
            # 記錄改善（記得 before/after）
            for imp in improvements:
                self.improvement_history.append({
                    "iteration": iteration,
                    "dimension": weak_dim,
                    "improvement": imp,
                    "applied": False
                })
            
            print(f"  → {len(improvements)} improvement(s) generated")
            
            # TODO: 實際應用改善（這裡是示範階段）
            # 在實際實現中，這裡會：
            # 1. 呼叫 LLM 生成代碼
            # 2. 應用修改到 repo
            # 3. 執行測試驗證
            
            # Tool: 重新評估
            print("\n🔧 Tool: Re-evaluating...")
            new_result = self.tool_evaluator.evaluate_all_tools()
            new_score = new_result.get("tool_overall", current_score)
            
            # LLM: 決策
            decision = self.llm_analyzer.make_decision(current_score, new_score)
            print(f"\n🤖 LLM Decision: {decision}")
            
            if decision == "KEEP":
                baseline = new_result
                current_score = new_score
                
                # 記錄 Evolution
                for imp in self.improvement_history[-len(improvements):]:
                    self.dashboard.add_evolution(
                        iteration=iteration,
                        before=f"No {imp['dimension']}",
                        after=f"Optimized {imp['dimension']}",
                        category=imp["dimension"].title(),
                        description=imp["improvement"]["action"]
                    )
                
                if current_score > best_score:
                    best_score = current_score
                    print(f"🎉 New best: {best_score}")
            else:
                print(f"↩️ Reverted")
            
            # 更新 Dashboard
            self.dashboard.update_debt_trend(iteration, current_score)
            
            if current_score >= self.target_score:
                print(f"\n✅ TARGET REACHED: {current_score}")
                break
        
        # 最終報告
        print("\n" + "=" * 60)
        print("FINAL DASHBOARD REPORT")
        print("=" * 60)
        
        print(self.dashboard.generate_report())
        
        print(f"\n📊 Summary:")
        print(f"  - Baseline: {baseline.get('tool_overall', 0):.1f}")
        print(f"  - Final: {current_score:.1f}")
        print(f"  - Best: {best_score:.1f}")
        print(f"  - Iterations: {iteration}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="AutoResearch Quality Loop")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--iterations", type=int, default=5, help="Max iterations")
    parser.add_argument("--target", type=int, default=80, help="Target score")
    
    args = parser.parse_args()
    
    loop = AutoResearchLoop(args.repo)
    loop.max_iterations = args.iterations
    loop.target_score = args.target
    
    loop.run()