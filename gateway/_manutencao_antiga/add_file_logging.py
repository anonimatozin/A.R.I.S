with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the debug prints with file logging
old_code = '''                try:
                    print(f"DEBUG: Calling create_user with token={token[:10]}..., username={username}, role={role}")
                    result = create_user(token, username, password, role, expires_at)
                    print(f"DEBUG: create_user returned: {result}")
                except Exception as e:
                    import traceback
                    print(f"DEBUG ERROR in create_user: {e}")
                    traceback.print_exc()
                    self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)
                    return'''

new_code = '''                try:
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: Calling create_user with token={token[:10]}..., username={username}, role={role}\\n")
                    result = create_user(token, username, password, role, expires_at)
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG: create_user returned: {result}\\n")
                except Exception as e:
                    import traceback
                    with open("debug_create_user.log", "a") as f:
                        f.write(f"DEBUG ERROR in create_user: {e}\\n")
                        traceback.print_exc(file=open("debug_create_user.log", "a"))
                    self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)
                    return'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Added file logging!")
else:
    print("Pattern not found!")