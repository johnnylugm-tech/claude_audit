#!/usr/bin/env python3
"""
MiniMax API Test
"""

import json
import urllib.request
import urllib.error

API_KEY = "sk-cp-9CZDgJY_biRMLWZxcwR9UkV8w5nglH55i577IY1DVKdKkcW1jAJsENTjYVp_sbzLpZddcdrw9HKiwX_64hm_DvrMK952ztYj0aodGuy5LXRb2Qj8zBLS-KU"
BASE_URL = "https://api.minimax.chat/v1"
MODEL = "abab6.5s-chat"

url = f"{BASE_URL}/text/chatcompletion_v2"

data = json.dumps({
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "你是一個助手"},
        {"role": "user", "content": "說 'OK'"}
    ],
    "temperature": 0.7
}).encode('utf-8')

req = urllib.request.Request(
    url,
    data=data,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
)

try:
    with urllib.request.urlopen(req, timeout=60) as response:
        result = response.read().decode('utf-8')
        print("Raw response:")
        print(result)
        print("\n" + "="*50)
        parsed = json.loads(result)
        print("Parsed:")
        print(json.dumps(parsed, indent=2))
except Exception as e:
    print(f"Error: {e}")