with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "r", encoding="utf-8") as f:
    content = f.read()

# Check for tabs
lines = content.split('\n')
for i, line in enumerate(lines, 1):
    if '\t' in line:
        print(f"Line {i} has TAB: {repr(line[:80])}")

# Also check line 307 specifically
lines = content.split('\n')
print(f"Line 307: {repr(lines[306])}")
print(f"Line 306: {repr(lines[305])}")
print(f"Line 308: {repr(lines[307])}")