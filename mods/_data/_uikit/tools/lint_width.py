import ast, sys, re, os
files = sys.argv[1:]
for f in files:
    src = open(f).read(); tree = ast.parse(src); lines = src.splitlines(); out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
            spec = "".join(c.value if isinstance(c, ast.Constant) else "{}" for c in node.format_spec.values)
            if not re.search(r"[<>^]?\d+|[<>^]\{\}", spec): continue
            if re.search(r"[fdxXeEg%]$", spec): continue        # 숫자 서식
            expr = ast.get_source_segment(src, node.value)
            out.append((node.lineno, spec, expr))
    print(f"== {f}: 문자열 폭 서식 {len(out)}건")
    for ln, spec, expr in out[:60]:
        print(f"  {ln:>4} {{{expr}:{spec}}}  | {lines[ln-1].strip()[:100]}")
