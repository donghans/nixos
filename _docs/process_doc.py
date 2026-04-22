import sys
import re

path, title = sys.argv[1], sys.argv[2]
lines = open(path).read().splitlines(keepends=True)

docs_root = '_docs/content'

def inline(m):
    p = f"{docs_root}/{m.group(1)}"
    try: return open(p).read().rstrip()
    except: return m.group(0)

content = ''.join(lines)
content = re.sub(r'--8<-- "([^"]+)"', inline, content)
lines = content.splitlines(keepends=True)

for i, l in enumerate(lines):
    if l.startswith('# '):
        nxt = lines[i+1] if i+1 < len(lines) else ''
        lines = lines[:i] + (lines[i+2:] if nxt.strip() == '' else lines[i+1:])
        break

content = ''.join(lines)
content = re.sub(r'\]\(([^)]+?)\.md(#[^)]*)?\)', lambda m: f']({m.group(1)}{m.group(2) or ""})', content)
out = f'---\ntitle: "{title}"\n---\n\n' + content
open(path, 'w').write(out)
