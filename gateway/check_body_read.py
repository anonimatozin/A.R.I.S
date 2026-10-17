with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

start = max(0, 47450)
end = min(len(content), 47800)
print(content[start:end])