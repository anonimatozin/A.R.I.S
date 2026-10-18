import re

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the POST handler (second occurrence)
matches = list(re.finditer(r'if path == "/api/users":', content))
if len(matches) < 2:
    print("Less than 2 occurrences found")
    exit(1)

idx = matches[1].start()
block_end = content.find("\n        if path ==", matches[1].start() + 1)
if block_end == -1:
    block_end = content.find("\n    def ", matches[1].start() + 1)
if block_end == -1:
    block_end = len(content)

old_block = content[matches[1].start():block_end]

# Wrap the entire block in try/except
lines = old_block.split('\n')
# Find the indentation of the first line
first_line = lines[0]
base_indent = len(first_line) - len(first_line.lstrip())

# Wrap in try/except
new_lines = []
for i, line in enumerate(lines):
    if i == 0:
        new_lines.append('            try:')
        new_lines.append(line)
    else:
        new_lines.append('    ' + line)

# Add except clause at the end
new_lines.append('        except Exception as e:')
new_lines.append('            self._send_json({"ok": False, "error": f"Erro no handler users: {e}"}, 500)')
new_lines.append('            return')

new_block = '\n'.join(new_lines)

# Replace
new_content = content[:matches[1].start()] + new_block + content[block_end:]

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "w", encoding="utf-8") as f:
    f.write(new_content)

print("Wrapped /api/users POST handler in try/except")