with open('cll1_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the auth() function
idx = content.find('async function auth()')
if idx >= 0:
    with open('auth_function.txt', 'w', encoding='utf-8') as f:
        f.write(content[idx:idx+2000])
    print('Written to auth_function.txt')
else:
    print('Not found')