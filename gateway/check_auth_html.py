with open('cll1_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()
idx = content.find('<div id="auth-overlay"')
if idx >= 0:
    with open('auth_overlay_html.txt', 'w', encoding='utf-8') as f:
        f.write(content[idx:idx+2000])
    print('Written to auth_overlay_html.txt')
else:
    print('Not found')