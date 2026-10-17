with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = 47096
block = content[idx:idx+3000]
print(block[:2000])