#!/usr/bin/env python3
"""
Project Quality Health Dashboard
================================
- Technical Debt Trend Chart: Visualizes debt reduction over iterations
- Hotspot Map: Identifies vulnerable/error-prone modules
- Evolution Report: Lists AI-optimized coding habits
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# ============================================================================
# Data Storage
# ============================================================================

class QualityDataStore:
    """Data storage for quality metrics"""
    
    def __init__(self, data_file: str = "quality_data.json"):
        self.data_file = data_file
        self.data = self._load()
    
    def _load(self) -> Dict:
        if Path(self.data_file).exists():
            with open(self.data_file, 'r') as f:
                return json.load(f)
        return {
            "iterations": [],
            "modules": {},  # module_name -> {issues, complexity, debt}
            "evolutions": []  # {iteration, before, after, description}
        }
    
    def _save(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    def add_iteration(self, iteration: int, metrics: Dict):
        """Add iteration metrics"""
        self.data["iterations"].append({
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            **metrics
        })
        self._save()
    
    def add_module_health(self, module: str, health: Dict):
        """Update module health data"""
        self.data["modules"][module] = health
        self._save()
    
    def add_evolution(self, evolution: Dict):
        """Add evolution record"""
        self.data["evolutions"].append(evolution)
        self._save()
    
    def get_iterations(self) -> List[Dict]:
        return self.data.get("iterations", [])
    
    def get_modules(self) -> Dict:
        return self.data.get("modules", {})
    
    def get_evolutions(self) -> List[Dict]:
        return self.data.get("evolutions", [])


# ============================================================================
# Technical Debt Tracker
# ============================================================================

class TechnicalDebtTracker:
    """Tracks and visualizes technical debt over time"""
    
    def __init__(self, datastore: QualityDataStore):
        self.datastore = datastore
    
    def add_debt_score(self, iteration: int, debt_score: float):
        """Record debt score for an iteration"""
        self.datastore.add_iteration(iteration, {"debt_score": debt_score})
    
    def get_trend_data(self) -> List[Dict]:
        """Get trend data for chart"""
        return self.datastore.get_iterations()
    
    def generate_chart(self) -> str:
        """Generate ASCII trend chart"""
        iterations = self.get_trend_data()
        if not iterations:
            return "No data yet. Run some iterations first."
        
        # Find max for scaling
        max_score = max(i.get("debt_score", 0) for i in iterations)
        max_score = max(max_score, 1)  # Avoid division by zero
        
        chart = ["\n📈 Technical Debt Trend", "=" * 50]
        
        for i, it in enumerate(iterations):
            score = it.get("debt_score", 0)
            bar_len = int((score / max_score) * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            chart.append(f"Iteration {it['iteration']:2d} | {bar} | {score:5.1f}")
        
        # Calculate trend
        if len(iterations) >= 2:
            first = iterations[0].get("debt_score", 0)
            last = iterations[-1].get("debt_score", 0)
            change = last - first
            trend = "📉" if change < 0 else "📈"
            chart.append(f"\nTrend: {trend} {abs(change):.1f} points ({'improved' if change < 0 else 'increased'})")
        
        return "\n".join(chart)


# ============================================================================
# Hotspot Map
# ============================================================================

class HotspotMap:
    """Identifies and visualizes vulnerable modules"""
    
    def __init__(self, datastore: QualityDataStore):
        self.datastore = datastore
    
    def add_module(self, module_name: str, issues: int, complexity: int, debt: int):
        """Add module health data"""
        self.datastore.add_module_health(module_name, {
            "issues": issues,
            "complexity": complexity,
            "debt": debt,
            "hotspot_score": (issues * 0.5) + (complexity * 0.3) + (debt * 0.2)
        })
    
    def get_hotspots(self) -> List[tuple]:
        """Get sorted hotspots (highest first)"""
        modules = self.datastore.get_modules()
        return sorted(
            [(m, d.get("hotspot_score", 0)) for m, d in modules.items()],
            key=lambda x: x[1],
            reverse=True
        )
    
    def generate_map(self) -> str:
        """Generate ASCII hotspot map"""
        hotspots = self.get_hotspots()
        if not hotspots:
            return "No modules tracked yet."
        
        # Find max score for scaling
        max_score = max(h[1] for h in hotspots) if hotspots else 1
        
        map_output = ["\n🔥 Hotspot Map (Most Vulnerable Modules)", "=" * 50]
        
        for i, (module, score) in enumerate(hotspots[:10]):  # Top 10
            bar_len = int((score / max_score) * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            
            # Add severity indicator
            if score > max_score * 0.7:
                severity = "🔴 CRITICAL"
            elif score > max_score * 0.4:
                severity = "🟡 WARNING"
            else:
                severity = "🟢 OK"
            
            map_output.append(f"{i+1:2d}. {module:25s} | {bar} | {score:5.1f} {severity}")
        
        # Summary
        critical = sum(1 for _, s in hotspots if s > max_score * 0.7)
        warning = sum(1 for _, s in hotspots if max_score * 0.4 < s <= max_score * 0.7)
        
        map_output.append(f"\n📊 Summary: {critical} critical, {warning} warnings")
        
        return "\n".join(map_output)


# ============================================================================
# Evolution Report
# ============================================================================

class EvolutionReport:
    """Tracks AI-optimized coding habits"""
    
    def __init__(self, datastore: QualityDataStore):
        self.datastore = datastore
    
    def add_evolution(self, iteration: int, category: str, before: str, after: str, description: str):
        """Add evolution record"""
        self.datastore.add_evolution({
            "iteration": iteration,
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "before": before,
            "after": after,
            "description": description
        })
    
    def get_report(self) -> str:
        """Generate evolution report"""
        evolutions = self.datastore.get_evolutions()
        if not evolutions:
            return "No evolutions recorded yet."
        
        # Group by category
        by_category = {}
        for e in evolutions:
            cat = e.get("category", "Other")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(e)
        
        report = ["\n🚀 Evolution Report (AI-Optimized Coding Habits)", "=" * 50]
        
        # Statistics
        total = len(evolutions)
        categories = len(by_category)
        
        report.append(f"\n📊 Statistics:")
        report.append(f"  - Total evolutions: {total}")
        report.append(f"  - Categories improved: {categories}")
        
        # By category
        for category, items in by_category.items():
            report.append(f"\n📁 {category} ({len(items)} improvements)")
            report.append("-" * 40)
            
            for item in items:
                report.append(f"  • {item['description']}")
                report.append(f"    Before: {item['before']}")
                report.append(f"    After:  {item['after']}")
        
        return "\n".join(report)


# ============================================================================
# Dashboard
# ============================================================================

class QualityDashboard:
    """Main dashboard combining all components"""
    
    def __init__(self, data_file: str = "quality_data.json"):
        self.datastore = QualityDataStore(data_file)
        self.debt_tracker = TechnicalDebtTracker(self.datastore)
        self.hotspot_map = HotspotMap(self.datastore)
        self.evolution_report = EvolutionReport(self.datastore)
    
    def run_full_dashboard(self) -> str:
        """Generate full dashboard report"""
        return (
            self.get_header() +
            self.debt_tracker.generate_chart() +
            "\n" +
            self.hotspot_map.generate_map() +
            "\n" +
            self.evolution_report.get_report()
        )
    
    def get_header(self) -> str:
        return """
╔══════════════════════════════════════════════════════════════════╗
║          Project Quality Health Dashboard                  ║
║          專案品質健康監控儀表板                            ║
╚══════════════════════════════════════════════════════════════════╝
"""
    
    def demo_data(self):
        """Add demo data for visualization"""
        # Technical debt trend
        for i in range(1, 6):
            self.debt_tracker.add_debt_score(i, 100 - (i * 15) + (i % 2) * 5)
        
        # Hotspot modules
        self.hotspot_map.add_module("phase_auditor.py", issues=12, complexity=8, debt=15)
        self.hotspot_map.add_module("audit.sh", issues=5, complexity=3, debt=8)
        self.hotspot_map.add_module("config.py", issues=2, complexity=1, debt=3)
        self.hotspot_map.add_module("utils.py", issues=8, complexity=6, debt=10)
        
        # Evolutions
        self.evolution_report.add_evolution(
            iteration=1,
            category="File Handling",
            before="Manual file close: file.close()",
            after="Context manager: with open() as f:",
            description="Replaced manual file closing with context managers"
        )
        self.evolution_report.add_evolution(
            iteration=1,
            category="Error Handling",
            before="Silent exception: except: pass",
            after="Proper logging: except Exception as e: log.error(e)",
            description="Added proper error handling with logging"
        )
        self.evolution_report.add_evolution(
            iteration=2,
            category="Type Safety",
            before="Implicit any: def parse(data)",
            after="Type hints: def parse(data: dict) -> list:",
            description="Added type annotations to function signatures"
        )
        self.evolution_report.add_evolution(
            iteration=2,
            category="Code Structure",
            before="Long function: def process() with 100 lines",
            after="Split into: def validate(), def transform(), def output()",
            description="Split large functions into smaller, focused functions"
        )
        self.evolution_report.add_evolution(
            iteration=3,
            category="Testing",
            before="No tests: pass",
            after="pytest unit tests with assertions",
            description="Added comprehensive test coverage"
        )


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Quality Dashboard")
    parser.add_argument("--add-iteration", type=int, help="Add iteration number")
    parser.add_argument("--debt", type=float, help="Add debt score")
    parser.add_argument("--module", type=str, help="Module name")
    parser.add_argument("--issues", type=int, help="Number of issues")
    parser.add_argument("--complexity", type=int, help="Complexity score")
    parser.add_argument("--module-debt", type=int, help="Module debt score")
    parser.add_argument("--add-evolution", action="store_true", help="Add evolution (use --before/--after)")
    parser.add_argument("--before", type=str, help="Before state")
    parser.add_argument("--after", type=str, help="After state")
    parser.add_argument("--category", type=str, help="Evolution category")
    parser.add_argument("--description", type=str, help="Evolution description")
    parser.add_argument("--demo", action="store_true", help="Load demo data")
    
    args = parser.parse_args()
    
    dashboard = QualityDashboard()
    
    if args.demo:
        dashboard.demo_data()
        print("✅ Demo data loaded")
    
    if args.add_iteration is not None and args.debt is not None:
        dashboard.debt_tracker.add_debt_score(args.add_iteration, args.debt)
        print(f"✅ Added iteration {args.add_iteration} with debt {args.debt}")
    
    if args.module and args.issues is not None:
        complexity = args.complexity or 0
        module_debt = args.module_debt or 0
        dashboard.hotspot_map.add_module(args.module, args.issues, complexity, module_debt)
        print(f"✅ Added module {args.module}")
    
    if args.add_evolution and args.before and args.after:
        dashboard.evolution_report.add_evolution(
            iteration=1,
            category=args.category or "Other",
            before=args.before,
            after=args.after,
            description=args.description or "Manual improvement"
        )
        print(f"✅ Added evolution record")
    
    # Always show dashboard
    print(dashboard.run_full_dashboard())