with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\auth.py", "rb") as f:
    content = f.read()

idx = content.find(b"def create_user")
if idx >= 0:
    print(content[idx:idx+300])
else:
    print("Not found")