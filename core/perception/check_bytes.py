with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()

idx = content.find(b"def _stt_loop")
if idx >= 0:
    start = max(0, idx - 100)
    end = min(len(content), idx + 100)
    print(content[start:end])
    print("---")
    print(f"Found at byte index: {idx}")
    
    context = content[max(0, idx-200):idx+200]
    if b'\t' in context:
        print("TABS FOUND in context!")
        for i, b in enumerate(context):
            if b == 9:
                print(f"  Tab at offset {i} (absolute {max(0, idx-200)+i})")

print("\nFull file tab check:")
with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()
    tab_positions = [i for i, b in enumerate(content) if b == 9]
    if tab_positions:
        print(f"Total tabs in file: {len(tab_positions)}")
        for pos in tab_positions[:20]:
            start = max(0, pos-20)
            end = min(len(content), pos+20)
            print(f"  Tab at {pos}: ...{content[start:end]}...")
    else:
        print("No tabs in file")