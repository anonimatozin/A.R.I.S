with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the corrupted section
idx_start = content.find("# --- User Management (admin only) ---")
idx_end = content.find("        if path == \"/api/users/cleanup\":")
if idx_start >= 0 and idx_end >= 0:
    print(f"Found at {idx_start} to {idx_end}")
    print(content[idx_start:idx_end+50])
else:
    print("Not found")