with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()

idx = content.find(b"class ContinuousVoiceSensor")
if idx >= 0:
    start = max(0, idx - 50)
    end = min(len(content), idx + 200)
    print(content[start:end])
    print("---")
    print(f"Class found at byte index: {idx}")
    
    # Check indentation of class
    line_start = content.rfind(b'\n', 0, idx) + 1
    line_end = content.find(b'\n', idx)
    if line_end == -1:
        line_end = len(content)
    class_line = content[line_start:line_end]
    print(f"Class line: {class_line}")
    print(f"Class line indent: {len(class_line) - len(class_line.lstrip())}")