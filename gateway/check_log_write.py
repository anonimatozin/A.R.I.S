with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('with open("debug_create_user.log"')
if idx >= 0:
    print(content[max(0, idx-200):idx+500])
else:
    print("NOT FOUND")