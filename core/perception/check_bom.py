with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\core\perception\continuous_voice_sensor.py", "rb") as f:
    content = f.read()

# Check for BOM
print(f"First 10 bytes: {content[:10]}")
print(f"Starts with BOM: {content.startswith(b'\xef\xbb\xbf')}")

# Check if there are any non-ASCII characters in the first 1000 bytes
for i, b in enumerate(content[:200]):
    if b > 127:
        print(f"Non-ASCII at byte {i}: {content[i]} = {chr(b)} (0x{b:02x})")

# Check for any weird whitespace
for i, b in enumerate(content[:500]):
    if b in (9, 11, 12, 13):  # tab, vertical tab, form feed, carriage return
        if b != 10:  # not newline
            print(f"Whitespace char at {i}: 0x{b:02x} ({chr(b) if b < 128 else 'non-ascii'})")