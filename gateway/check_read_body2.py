with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find all occurrences of _read_body
import re
for m in __import__('re').finditer(r'_read_body\(\)', content):
    start = max(0, m.start()-80)
    end = min(len(content), m.end()+80)
    print(f"Found at {m.start()}:")
    print(content[max(0, m.start()-100):m.end()+100])
    print("---")