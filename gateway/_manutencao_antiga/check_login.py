with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('path == "/api/login"')
if idx >= 0:
    print(content[idx:idx+500])
else:
    print("NOT FOUND")