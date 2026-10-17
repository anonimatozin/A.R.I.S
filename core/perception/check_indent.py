with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i, line in enumerate(lines[305:310], start=306):
    print(f"Line {i}: {repr(line[:50])}")

# Check for tabs vs spaces
for i, line in enumerate(lines[305:315], start=306):
    if '\t' in line:
        print(f"Line {i} has TAB: {repr(line[:50])}")