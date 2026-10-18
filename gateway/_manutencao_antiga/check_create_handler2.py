with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('if action == "create":')
if idx >= 0:
    # Find the second occurrence (user management)
    idx2 = content.find('if action == "create":', idx + 1)
    if idx2 >= 0:
        print(content[idx2:idx2+1000])
    else:
        print("Second occurrence not found")
else:
    print("Not found")