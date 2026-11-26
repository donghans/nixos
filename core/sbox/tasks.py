#!/usr/bin/env python3
"""sbox 작업 선언(plan sbox-project-policy R6): 매니페스트의 [tasks.<이름>] → ct 의 /etc/sbox/tasks.json. 호스트에서 돈다(표준 라이브러리만).
[tasks.dev]  argv = ["npm","run","dev"] · cwd = "web"(작업 사본 기준 상대) · kind = "oneshot"|"service" · pins = ["package.json"](정의 파일, cwd 기준 아닌 작업 사본 기준 상대 경로) · timeout = 600
[tasks.dev.pinned]  "web/package.json" = "<sha256>"   ← 사람이 승인할 때 sbox 가 기록(--approve). 에이전트가 정의 파일을 바꾸면 이 값과 달라져 실행이 거부된다."""
import argparse, json, os, re, sys, tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import protect  # noqa: E402

NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,40}")
WORK = "/home/sbox/work"


def load(manifest):
    with open(manifest, "rb") as f:
        data = tomllib.load(f)
    tasks = data.get("tasks") or {}
    if not isinstance(tasks, dict):
        raise SystemExit("[tasks] 형식이 잘못됐습니다")
    out = {}
    for name, t in tasks.items():
        if not NAME_RE.fullmatch(name):
            raise SystemExit(f"작업 이름 {name!r} 은 소문자·숫자·-·_ 이고 41자 이하여야 합니다")
        argv = t.get("argv")
        if not (isinstance(argv, list) and argv and all(isinstance(x, str) and x for x in argv)):
            raise SystemExit(f"[tasks.{name}] argv 는 비어 있지 않은 문자열 목록이어야 합니다(셸 문자열이 아니라 인자 목록)")
        kind = t.get("kind", "oneshot")
        if kind not in ("oneshot", "service"):
            raise SystemExit(f"[tasks.{name}] kind 는 oneshot|service")
        for rel in [t.get("cwd", ".")] + list(t.get("pins") or []):
            if os.path.isabs(rel) or ".." in rel.split("/"):
                raise SystemExit(f"[tasks.{name}] 경로 {rel!r} 는 작업 사본 안의 상대 경로여야 합니다")
        out[name] = {"argv": argv, "kind": kind, "cwd": t.get("cwd", "."), "pins": list(t.get("pins") or []),
                     "pinned": dict(t.get("pinned") or {}), "timeout": int(t.get("timeout", 900)), "env": dict(t.get("env") or {})}
    return out


def protect_patterns(manifest):
    """보호 경로 패턴 = 기본 집합 + [protect] add − [protect] remove (policy R7·§3 ⑧). 매니페스트의 [protect] add/remove 는 상대 경로 패턴 목록."""
    with open(manifest, "rb") as f:
        sec = tomllib.load(f).get("protect") or {}
    add, rem = sec.get("add") or [], sec.get("remove") or []
    for k, v in (("add", add), ("remove", rem)):
        if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
            raise SystemExit(f"[protect] {k} 는 문자열 목록이어야 합니다")
    pats = [p for p in protect.DEFAULT_PROTECT if p not in rem] + [p for p in add if p not in protect.DEFAULT_PROTECT]
    for p in pats:
        if os.path.isabs(p) or ".." in p.split("/"):
            raise SystemExit(f"[protect] 패턴 {p!r} 는 작업 사본 안의 상대 경로여야 합니다")
    return pats


def needed(manifest):
    return sorted({p for t in load(manifest).values() for p in t["pins"]})


def build(manifest, digests, approve, protected=None):
    tasks, outcfg, newpins = load(manifest), {}, {}
    for name, t in tasks.items():
        pins = {}
        for rel in t["pins"]:
            cur = digests.get(rel)
            if cur is None:
                raise SystemExit(f"[tasks.{name}] 정의 파일 {rel} 을 ct 에서 읽지 못했습니다")
            ok = t["pinned"].get(rel)
            if approve:
                pins[rel] = cur; newpins.setdefault(name, {})[rel] = cur
            elif ok is None:
                raise SystemExit(f"[tasks.{name}] {rel} 가 아직 승인되지 않았습니다 — 내용을 확인하고 `sboxctl taskd NAME --approve`")
            elif ok != cur:
                raise SystemExit(f"[tasks.{name}] {rel} 가 승인 때와 다릅니다(승인 {ok[:12]}… / 지금 {cur[:12]}…) — 바뀐 내용을 확인하고 `--approve` 로 다시 승인하세요")
            else:
                pins[rel] = ok
        outcfg[name] = {"argv": t["argv"], "cwd": t["cwd"], "kind": t["kind"], "pins": pins, "timeout": t["timeout"], "env": t["env"]}
    return {"version": 1, "root": WORK, "home": "/var/lib/sbox-run", "logdir": "/var/log/sbox-taskd", "tasks": outcfg,
            "protect": protect_patterns(manifest), "protected": sorted(protected or [])}, newpins


def set_pinned(path, newpins):
    """매니페스트에 [tasks.<이름>.pinned] 표를 쓴다(그 표만 바꾸고 나머지 글자는 그대로)."""
    text = open(path, encoding="utf-8").read()
    for name, pins in newpins.items():
        head = f"[tasks.{name}.pinned]"
        text = re.sub(r"(?ms)^" + re.escape(head) + r"\n(?:(?!\[).*\n?)*", "", text)
        text = text.rstrip("\n") + f"\n\n{head}\n" + "".join(f"{json.dumps(k)} = {json.dumps(v)}\n" for k, v in sorted(pins.items()))
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(text)
    os.replace(tmp, path)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["needed", "build", "patterns"])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--digests"); ap.add_argument("--approve", action="store_true"); ap.add_argument("--out"); ap.add_argument("--protected")
    a = ap.parse_args(argv)
    if a.cmd == "needed":
        print(json.dumps(needed(a.manifest))); return 0
    if a.cmd == "patterns":
        print(json.dumps(protect_patterns(a.manifest))); return 0
    digests = json.load(open(a.digests)) if a.digests else {}
    cfg, newpins = build(a.manifest, digests, a.approve, json.load(open(a.protected)) if a.protected else [])
    json.dump(cfg, open(a.out, "w"), ensure_ascii=False, indent=1)
    if a.approve and newpins:
        set_pinned(a.manifest, newpins)
    print(json.dumps({"tasks": sorted(cfg["tasks"]), "approved": sorted(newpins)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
