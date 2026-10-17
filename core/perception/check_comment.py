with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()

# Find the comment line
idx = content.find(b"STT Loop")
if idx >= 0:
    start = max(0, idx - 50)
    end = min(len(content), idx + 100)
    print(f"Context around 'STT Loop':")
    print(content[max(0, idx-100):idx+100])
    print("---")
    
    # Check the exact bytes of the comment line
    line_start = content.rfind(b'\n', 0, idx) + 1
    line_end = content.find(b'\n', idx)
    if line_end == -1:
        line_end = len(content)
    comment_line = content[line_start:line_end]
    print(f"Comment line bytes: {comment_line}")
    print(f"Comment line length: {len(comment_line)}")
    print(f"Starts with spaces: {comment_line.startswith(b' ')}")
    print(f"Leading spaces: {len(comment_line) - len(comment_line.lstrip())}")

print("\n\nChecking line 305 (index 304 in 0-based):")
with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()
lines = content.split(b'\n')
for i in range(300, 315):
    if i < len(lines):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        print(f"Line {i+1} (idx {i}): indent={indent}, content={line[:80]}")