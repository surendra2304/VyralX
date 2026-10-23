import re

with open("app/main.py", encoding="utf-8") as f:
    content = f.read()

pattern = re.compile(r'@app\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)["\']', re.IGNORECASE)
matches = pattern.findall(content)

print(f"Total endpoints found: {len(matches)}")
for method, path in matches:
    print(f"{method.upper():6s} {path}")
