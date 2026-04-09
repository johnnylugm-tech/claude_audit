#!/usr/bin/env python3
"""
MiniMax LLM Integration for AutoResearch
==================================
使用 MiniMax API 進行代碼改善 - 直接讀取 api_config.env
"""

import os
import json
import urllib.request
import urllib.error
from pathlib import Path

# ============================================================================
# MiniMax API Client
# ============================================================================

API_KEY = "sk-cp-9CZDgJY_biRMLWZxcwR9UkV8w5nglH55i577IY1DVKdKkcW1jAJsENTjYVp_sbzLpZddcdrw9HKiwX_64hm_DvrMK952ztYj0aodGuy5LXRb2Qj8zBLS-KU"
BASE_URL = "https://api.minimax.chat/v1"
MODEL = "abab6.5s-chat"

class MiniMaxClient:
    """MiniMax API Client"""
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        self.api_key = api_key or API_KEY
        self.base_url = base_url or BASE_URL
        self.model = model or MODEL
        
        if not self.api_key:
            raise ValueError("API key not found")
    
    def chat(self, system: str, user: str, temperature: float = 0.7) -> str:
        """發送 Chat 請求"""
        
        url = f"{self.base_url}/text/chatcompletion_v2"
        
        data = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": temperature
        }).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            raise Exception(f"API Error: {e.code} - {e.read().decode()}")


# ============================================================================
# LLM-powered Improvement Agent
# ============================================================================

class LLMImprovementAgent:
    """使用 LLM 進行代碼改善"""
    
    def __init__(self, repo_path: str = "/workspace/claude_audit"):
        self.repo_path = Path(repo_path)
        self.client = MiniMaxClient()
    
    def improve_test_coverage(self) -> dict:
        """改善測試覆蓋率"""
        
        # 讀取現有代碼
        py_files = list(self.repo_path.glob("*.py"))
        main_file = None
        for f in py_files:
            if "test" not in f.name and f.suffix == ".py":
                main_file = f
                break
        
        if not main_file:
            return {"success": False, "error": "No main file found"}
        
        code = main_file.read_text()[:2000]  # 限制長度
        
        prompt = f"""
Generate a pytest test file for {main_file.name}.
The code to test:
{code}

Create at least 5 test functions covering:
- Basic functionality
- Edge cases
- Error handling

Output ONLY the python code, no explanation.
"""
        
        system = """你是一個專業的 Python developer，擅長編寫 pytest 測試。
只輸出 python 代碼，不要其他文字。使用標準 pytest 格式。
"""
        
        try:
            test_code = self.client.chat(system, prompt)
            
            # 提取代碼塊
            if "```python" in test_code:
                start = test_code.find("```python") + len("```python")
                end = test_code.find("```", start)
                test_code = test_code[start:end].strip()
            elif "```" in test_code:
                start = test_code.find("```") + 3
                end = test_code.find("```", start)
                test_code = test_code[start:end].strip()
            
            # 寫入測試檔案
            test_file = self.repo_path / "test_auditor.py"
            test_file.write_text(test_code)
            
            return {"success": True, "file": str(test_file)}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def improve_type_safety(self) -> dict:
        """改善類型安全"""
        
        py_files = list(self.repo_path.glob("*.py"))
        main_file = None
        for f in py_files:
            if "test" not in f.name and f.suffix == ".py":
                main_file = f
                break
        
        if not main_file:
            return {"success": False, "error": "No main file found"}
        
        code = main_file.read_text()[:2000]
        
        prompt = f"""
Add Python type hints to all functions in this code.
Use Python 3.9+ style (list, dict, not List, Dict).

Original code:
{code}

Output ONLY the modified python code, no explanation.
"""
        
        system = """你是一個專業的 Python developer，擅長添加類型註釋。
只輸出 python 代碼，不要其他文字。
"""
        
        try:
            improved_code = self.client.chat(system, prompt)
            
            # 提取代碼塊
            if "```python" in improved_code:
                start = improved_code.find("```python") + len("```python")
                end = improved_code.find("```", start)
                improved_code = improved_code[start:end].strip()
            elif "```" in improved_code:
                start = improved_code.find("```") + 3
                end = improved_code.find("```", start)
                improved_code = improved_code[start:end].strip()
            
            # 備份並寫入
            backup = main_file.with_suffix(".py.bak")
            backup.write_text(main_file.read_text())
            main_file.write_text(improved_code)
            
            return {"success": True, "file": str(main_file)}
        
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    agent = LLMImprovementAgent()
    
    print("=" * 50)
    print("Testing MiniMax API Connection")
    print("=" * 50)
    
    try:
        # Test chat
        response = agent.client.chat("你是一個助手", "說 'OK'")
        print(f"Chat Test: {response}")
        
        # Run improvements
        print("\n" + "=" * 50)
        print("Improving Test Coverage")
        print("=" * 50)
        
        result = agent.improve_test_coverage()
        print(f"Result: {result}")
        
    except Exception as e:
        print(f"❌ Error: {e}")