with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add more detailed logging
old_code = '''                try:
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: Calling create_user with token={token[:10]}..., username={username}, role={role}\n")
                    result = create_user(token, username, password, role, expires_at)
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: create_user returned: {result}\n")'''

new_code = '''                with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG ENTER: action=create, username={username}, has_pwd={bool(password)}, role={role}\\n")
                    try:
                        with open("debug_create_user.log", "a") as f:
                            f.write(f"DEBUG: Calling create_user with token={token[:10]}..., username={username}, role={role}\\n")
                        result = create_user(token, username, password, role, expires_at)
                        with open("debug_create_user.log", "a") as f:
                            f.write(f"DEBUG: create_user returned: {result}\\n")
                except Exception as e:'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Added more debug logging!")
else:
    print("Pattern not found!")