with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('# --- User Management (admin only) ---')
if idx >= 0:
    start = max(0, idx)
    end = min(len(content), idx + 2000)
    print(content[start:end])
else:
    print("Not found")