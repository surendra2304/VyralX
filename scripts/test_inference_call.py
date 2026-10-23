import json
import os
import urllib.request
from pathlib import Path

def get_env_var(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    env_file = Path("/etc/default/friday_universe.env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""

def test_clean_json():
    inf_url = get_env_var("INFERENCE_URL") or "http://10.0.0.121:8001"
    inf_key = get_env_var("INFERENCE_API_KEY")
    endpoint = f"{inf_url.rstrip('/')}/v1/chat/completions"
    
    prompt = (
        "Video: Cheetah jumps onto safari jeep in Africa.\n"
        "Duration: 22 seconds.\n"
        "Task: Write a 40-word viral commentary script.\n"
        "START DIRECTLY WITH '{' AND END WITH '}'. NO THINKING. NO MARKDOWN. NO PREAMBLE.\n"
        "{\n"
        '  "visual_summary": "Cheetah jumps onto safari jeep while tourists freeze",\n'
        '  "script": "spoken script here",\n'
        '  "title": "When A Wild Cheetah Jumps On Your Jeep #Shorts",\n'
        '  "cyan_keywords": ["CHEETAH", "SAFARI", "JEEP", "FROZEN"],\n'
        '  "debate_question": "Would you stay calm or panic in this jeep?",\n'
        '  "tags": ["shorts", "cheetah", "viral"]\n'
        "}"
    )
    
    payload = {
        "model": "groq",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5,
        "max_tokens": 1000
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-INFERENCE-API-KEY": inf_key
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            print("Model:", data.get("model"))
            content = data["choices"][0]["message"]["content"]
            print("Content:\n", content)
    except Exception as e:
        print(f"Call failed: {e}")

if __name__ == "__main__":
    test_clean_json()
