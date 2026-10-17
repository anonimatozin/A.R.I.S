with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "r", encoding="utf-8") as f:
    content = f.read()

# Check lines around 307
lines = content.split('\n')
for i, line in enumerate(lines[305:315], start=306):
    if '\t' in line:
        print(f"Line {i} has TAB: {repr(line)}")
    else:
        print(f"Line {i}: {repr(line)}")

# Check exact indentation of line 307 (index 306)
line_307 = lines[306]
print(f"\nLine 307 repr: {repr(line_307)}")
print(f"Line 307 starts with: '{line_307[:10]}'")
print(f"Line 307 indent length: {len(line_307) - len(line_307.lstrip())}")

# Check previous line
line_306 = lines[305]
print(f"\nLine 306 repr: {repr(line_306)}")
print(f"Line 306 indent length: {len(line_306) - len(line_306.lstrip())}")