with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('if action == "create":')
if idx >= 0:
    print(content[idx:idx+1000])
else:
    print("Not found")