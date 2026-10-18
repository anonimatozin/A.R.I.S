import re

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the user creation handler and wrap it in try/except
old_code = '''                if action == "create":
                from gateway.auth import create_user
                username = body.get("username", "")
                password = body.get("password", "")
                role = body.get("role", "bicicleta-com-rodinhas")
                expires_at = body.get("expires_at")
                if not username or not password:
                    self._send_json({"ok": False, "error": "username e password obrigat\u00f3rios"}, 400)
                    return
                if expires_at is not None:
                    try:
                        expires_at = float(expires_at)
                    except (ValueError, TypeError):
                        self._send_json({"ok": False, "error": "expires_at deve ser timestamp num\u00e9rico"}, 400)
                        return
                    try:

                        result = create_user(token, username, password, role, expires_at)

                    except Exception as e:

                        self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)

                    return

                self._send_json(result)
                return'''

new_code = '''                try:
                    from gateway.auth import create_user
                    username = body.get("username", "")
                    password = body.get("password", "")
                    role = body.get("role", "bicicleta-com-rodinhas")
                    expires_at = body.get("expires_at")
                    if not username or not password:
                        self._send_json({"ok": False, "error": "username e password obrigat\u00f3rios"}, 400)
                        return
                    if expires_at is not None:
                        try:
                            expires_at = float(expires_at)
                        except (ValueError, TypeError):
                            self._send_json({"ok": False, "error": "expires_at deve ser timestamp num\u00e9rico"}, 400)
                            return
                    try:
                        result = create_user(token, username, password, role, expires_at)
                    except Exception as e:
                        self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)
                        return
                    self._send_json(result)
                    return'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed!")
else:
    print("Pattern not found!")
    # Show context around the pattern
    idx = content.find('if action == "create":')
    if idx >= 0:
        print(content[max(0, idx-100):idx+500])
    else:
        print("Not found at all")