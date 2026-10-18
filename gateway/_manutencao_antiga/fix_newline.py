with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix the missing newline before next handler
old = '            return        if path == "/api/users/cleanup":'
new = '            return\n        if path == "/api/users/cleanup":'

if old in content:
    content = content.replace(old, new)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed!")
else:
    print("Pattern not found")