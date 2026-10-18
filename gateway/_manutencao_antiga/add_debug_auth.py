with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\auth.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add debug logging to create_user function
old_code = '''def create_user(requesting_token: str, username: str, password: str, role: str = DEFAULT_ROLE, expires_at: float | None = None) -> dict:
    """Cria novo usu�rio (apenas admin/power-user)."""
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    if role not in ROLES:'''

new_code = '''def create_user(requesting_token: str, username: str, password: str, role: str = DEFAULT_ROLE, expires_at: float | None = None) -> dict:
    """Cria novo usu�rio (apenas admin/power-user)."""
    print(f"DEBUG create_user called: username={username}, role={role}")
    import traceback
    traceback.print_stack()
    err = require_permission(requesting_token, "user_create")
    if err:
        return err

    if role not in ROLES:'''

if old_code in content:
    content = content.replace(old_code, new_code)
    with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\auth.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("Added debug to auth.py!")
else:
    print("Pattern not found!")