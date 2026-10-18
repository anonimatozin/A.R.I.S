with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find("body = self._read_body()")
if idx >= 0:
    print(content[max(0, idx-100):idx+200])
else:
    print("Not found")