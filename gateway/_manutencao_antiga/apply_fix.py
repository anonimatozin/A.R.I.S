import re

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Wrap the entire /api/users POST handler in try/except
old_block = '''        if path == "/api/users":
            err = self._check_auth()
            if err:
                self._send_json(err, 401)
                return
            token = self._get_token()
            if self.command == "GET":
                from gateway.auth import list_users
                result = list_users(token)
                self._send_json(result)
                return
            body = self._read_body()
            action = body.get("action", "create")
            if action == "create":
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

new_block = '''        if path == "/api/users":
            try:
                err = self._check_auth()
                if err:
                    self._send_json(err, 401)
                    return
                token = self._get_token()
                if self.command == "GET":
                    from gateway.auth import list_users
                    result = list_users(token)
                    self._send_json(result)
                    return
                try:
                    body = self._read_body()
                except Exception as e:
                    self._send_json({"ok": False, "error": f"Erro ao ler body: {e}"}, 400)
                    return
                action = body.get("action", "create")
                if action == "create":
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

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed!")
else:
    print("Pattern not found!")
    # Show what we're looking for
    import re
    matches = list(re.finditer(r'if path == "/api/users":', content))
    for m in matches:
        start = max(0, m.start()-50)
        print(f"Found at {m.start()}: ...{content[start:m.start()+200]}...")