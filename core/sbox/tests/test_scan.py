#!/usr/bin/env python3
"""scan.py(저장소 → 송신 프리셋 제안)와 매니페스트 [resources] disk(tools.resource) 시험 — plan dev-sandbox-pilot §29-44.
지키는 것: 제안은 읽기만 한다 · 이미 허용되는 것(always·자동·매니페스트)은 제안에서 빠진다 · 모르는 레지스트리·변수 이미지는 조용히 넘기지 않고 따로 보고한다 ·
[resources] 는 매니페스트를 다시 써도 보존되고 잘못된 disk 값은 실패한다. 실행: python3 -I core/sbox/tests/test_scan.py"""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import egress, scan, tools  # noqa: E402

n = {"ok": 0, "bad": 0}
def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond: print("  FAIL", name, extra)

d = tempfile.mkdtemp()
open(os.path.join(d, "Dockerfile"), "w").write("""FROM ghcr.io/astral-sh/uv:0.9-alpine AS uv
FROM node:22-alpine AS build
RUN apk add git && npm ci
FROM mcr.microsoft.com/dotnet/aspnet:8.0
RUN apt-get update && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && curl https://cdn.sheetjs.com/x.tgz -o x
FROM ${BASE}
""")
open(os.path.join(d, "docker-compose.yml"), "w").write("services:\n  a:\n    image: quay.io/foo/bar:1\n")
os.makedirs(os.path.join(d, "node_modules", "x")); open(os.path.join(d, "node_modules", "x", "Dockerfile"), "w").write("FROM evil.example/x\n")
r = scan.filter_known(scan.scan(d), None)
check("alpine·ghcr·nodesource 제안", {"alpine", "ghcr", "nodesource"} <= set(r["presets"]), r["presets"])
check("Docker 허브·always(docker) 는 제안에서 빠짐", "docker" not in r["presets"])
check("프리셋 밖 URL 은 egress 후보", "cdn.sheetjs.com" in r["egress"] and "deb.nodesource.com" not in r["egress"], r["egress"])
check("모르는 레지스트리 보고", "mcr.microsoft.com" in r["unknown_registries"] and "quay.io" in r["unknown_registries"], r["unknown_registries"])
check("변수 이미지는 조용히 넘기지 않음", "(변수로 정한 기반 이미지)" in r["unknown_registries"])
check("node_modules 안은 안 읽음", "evil.example" not in r["unknown_registries"])
# 매니페스트에 이미 있는 것은 제안에서 빠진다
mp = os.path.join(d, "m.toml")
tools.write_manifest(mp, "p", d, {"node": {"spec": "22", "source": "t"}}, {}, {}, network={"presets": ["alpine"], "egress": ["cdn.sheetjs.com"]})
r2 = scan.filter_known(scan.scan(d), mp)
check("매니페스트 presets·egress·자동(node) 제외", "alpine" not in r2["presets"] and "cdn.sheetjs.com" not in r2["egress"] and "node" not in r2["presets"], r2)
check("남은 것은 제안", "ghcr" in r2["presets"])
# [resources]
tools.write_manifest(mp, "p", d, {}, {}, {}, resources={"disk": "20GiB"})
check("disk 읽기", tools.resource(mp, "disk") == "20GiB")
check("없는 키·없는 파일은 None", tools.resource(mp, "cpu") is None and tools.resource("/nonexistent", "disk") is None)
tools.write_manifest(mp, "p", d, {}, {}, {}, resources={"disk": "20G"})
try:
    tools.resource(mp, "disk"); bad = False
except SystemExit:
    bad = True
check("잘못된 disk 는 실패", bad)
print(f"{n['ok']} 통과 / {n['bad']} 실패"); sys.exit(1 if n["bad"] else 0)
