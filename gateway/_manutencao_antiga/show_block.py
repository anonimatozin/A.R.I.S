with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find all occurrences of "/api/users"
import re
for m in re.finditer(r'/api/users', content):
    start = max(0, m.start() - 100)
    end = min(len(content), m.start() + 200)
    print(f"Found at {m.start()}:")
    print(content[max(0, m.start()-100):m.start()+200])
    print("---")