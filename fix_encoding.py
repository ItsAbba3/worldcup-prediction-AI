import re

with open('wc26_build_site.py', 'r', encoding='utf-8') as f:
    content = f.read()

# اول read_text() رو fix کن
fixed = re.sub(r'\.read_text\(\)', '.read_text(encoding="utf-8")', content)

# بعد write_text هایی که encoding ندارن رو fix کن
fixed = re.sub(
    r'\.write_text\(([^()]+?)\)',
    lambda m: f'.write_text({m.group(1)}, encoding="utf-8")'
    if 'encoding' not in m.group(1) else m.group(0),
    fixed
)

with open('wc26_build_site.py', 'w', encoding='utf-8') as f:
    f.write(fixed)

print('Done! حالا python wc26_build_site.py رو بزن')
