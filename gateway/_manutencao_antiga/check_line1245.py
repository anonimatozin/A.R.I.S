with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines[1240:1260], start=1241):
    print(f"Line {i}: {repr(line)}")