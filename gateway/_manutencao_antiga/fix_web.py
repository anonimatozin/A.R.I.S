# Find and fix the create_user call in web.py
import re

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the create_user call and wrap it with try/except
old_code = """                result = create_user(token, username, password, role, expires_at)
                  self._send_json(result)
                  return"""

new_code = """                try:
                      result = create_user(token, username, password, role, expires_at)
                  except Exception as e:
                      self._send_json({"ok": False, "error": f"Erro interno: {e}"}, 500)
                      return
                  self._send_json(result)
                  return"""

# Use regex to handle whitespace variations
import re
pattern = r'(\s+)result = create_user\(token, username, password, role, expires_at\)\s*\n\s*self\._send_json\(result\)\s*\n\s*return'

def replacement(match):
    indent = match.group(1)
    return f"""{indent}try:
{indent}    result = create_user(token, username, password, role, expires_at)
{indent}except Exception as e:
{indent}    self._send_json({{"ok": False, "error": f"Erro interno: {{e}}"}}, 500)
{indent}    return
{indent}self._send_json(result)
{indent}return"""

new_content = re.sub(pattern, replacement, content)

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("Fixed!")