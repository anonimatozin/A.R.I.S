import urllib.request

r = urllib.request.urlopen("http://192.168.0.106:8766/", timeout=5)
html = r.read().decode("utf-8", "ignore")
print(f"Size: {len(html)} bytes")
checks = ["Control Center", "Voice Interface", "Neural Network", "orbs-canvas", "modal-files", "modal-users", "auth-overlay", "cc-state-badge", "modal-files", "modal-users", "fc-fl", "uc-ul", "cc-state-badge", "cc-state-text", "cc-timer", "cc-uname", "cc-urole", "modal-files", "modal-users"]
for c in checks:
    print(f"  {c}: {c in html}")