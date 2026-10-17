with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the corrupted section
idx_start = content.find("# --- User Management (admin only) ---")
idx_end = content.find("        if path == \"/api/users/cleanup\":")
if idx_start >= 0 and idx_end >= 0:
    old = content[idx_start:idx_end]
    
    new = """        # --- User Management (admin only) ---
        if path == "/api/users":
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
                return
            elif action == "delete":
                from gateway.auth import delete_user
                username = body.get("username", "")
                if not username:
                    self._send_json({"ok": False, "error": "username obrigat\u00f3rio"}, 400)
                    return
                result = delete_user(token, username)
                self._send_json(result)
                return
            elif action == "change_role":
                from gateway.auth import change_role
                username = body.get("username", "")
                new_role = body.get("role", "")
                if not username or not new_role:
                    self._send_json({"ok": False, "error": "username e role obrigat\u00f3rios"}, 400)
                    return
                result = change_role(token, username, new_role)
                self._send_json(result)
                return
            self._send_json({"ok": False, "error": f"A\u00e7\u00e3o desconhecida: {action}"}, 400)
            return"""

    content = content[:content.find("# --- User Management (admin only) ---")] + new + content[content.find("        if path == \"/api/users/cleanup\""):]
    
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Fixed!")
else:
    print("Could not find boundaries")