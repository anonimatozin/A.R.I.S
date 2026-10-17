with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('if path == "/api/users":')
if idx >= 0:
    idx2 = content.find('if path == "/api/users":', idx + 1)
    if idx2 >= 0:
        block_end = content.find("\n        if path ==", idx2 + 1)
        if block_end == -1:
            block_end = content.find("\n    def ", idx2 + 1)
        if block_end == -1:
            block_end = len(content)
        block = content[idx2:block_end]
        print(block[:2000])
    else:
        print("Second occurrence not found")
else:
    print("Not found")