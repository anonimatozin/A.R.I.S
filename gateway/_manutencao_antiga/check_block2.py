import re

with open(r"C:\Users\Administrator\Documents\Default Project\ARIS\gateway\web.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the POST /api/users handler (second occurrence)
matches = list(re.finditer(r'if path == "/api/users":', content))
print(f"Found {len(matches)} occurrences")
for m in matches:
    print(f"  Found at {m.start()}")

# The second occurrence is the POST handler
if len(matches) >= 2:
    idx = matches[1].start()
    print(f"POST handler at {idx}")
    
    # Find the end of this block
    block_end = content.find("\n        if path ==", matches[1].start() + 1)
    if block_end == -1:
        block_end = content.find("\n    def ", matches[1].start() + 1)
    if block_end == -1:
        block_end = len(content)
    
    block = content[matches[1].start():block_end]
    print(f"Block length: {len(block)}")
    
    # Check if the block already has the try/except wrapper
    if "try:" in block[:200] and "except Exception as e:" in block:
        print("Already has try/except wrapper")
    else:
        print("Needs try/except wrapper")
        # Show first 500 chars
        print(block[:500])
else:
    print("Less than 2 occurrences found")