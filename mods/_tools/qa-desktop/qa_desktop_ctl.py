#!/usr/bin/env python3
"""qa-desktop-ctl — 화면 확인용 QA 데스크톱(incus VM)을 선언대로 만들고 점검한다.

  qa-desktop-ctl [--name 이름] ensure      없으면 만들고 프로비저닝한다. **이미 있는 VM 은 건드리지 않는다**(프로비저닝 표식이 없으면 「기존 VM 채택」으로 보고만).
                                           생성 도중 실패한 VM 은 `state=creating` 표식으로 알아보고 이어서 프로비저닝한다(멱등).
  qa-desktop-ctl [--name 이름] provision   기존 VM 에 프로비저닝 스크립트를 다시 실행한다(멱등; 선언의 규칙·버전을 바꾼 뒤 반영할 때)
  qa-desktop-ctl [--name 이름] status      상태·IP·접속·설정 일치 여부·스냅샷
  qa-desktop-ctl [--name 이름] snapshot <이름>
  qa-desktop-ctl [--name 이름] destroy --yes    VM 삭제(되돌릴 수 없음)

설정은 `--config <json>`(nix 가 선언에서 만든 파일, 기본: 환경변수 QA_DESKTOP_CONFIG)에서 읽는다:
  name · cpu · memory · disk · image · user · playwright · projects({이름: 데스크톱번호}) · ssh_key(호스트 개인키 경로) · provision(스크립트 경로) · tools_dir(ws.py·snap.py 디렉터리)
--name·--memory·--cpu·--disk 로 한 번만 바꿔 시험할 수 있다(운영 VM 과 겹치지 않는 이름으로).
VM 에는 사용자(`qa`) 키 접속만 연다. 호스트 키가 없으면 만든다(서비스를 돌리는 사용자 소유).
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time

KEY_NS = "user.qa-desktop"


def run(*cmd, check=True, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        sys.exit(f"명령 실패({' '.join(cmd[:3])}…): {(r.stderr or r.stdout).strip()[-400:]}")
    return r


def incus(*a, check=True, **kw):
    return run("incus", *a, check=check, **kw)


def log(msg):
    print(f"[qa-desktop-ctl {time.strftime('%T')}] {msg}", flush=True)


def load_config(a):
    path = a.config or os.environ.get("QA_DESKTOP_CONFIG")
    if not path:
        sys.exit("--config 또는 QA_DESKTOP_CONFIG 가 필요하다")
    cfg = json.load(open(path))
    for k in ("name", "cpu", "memory", "disk", "memory_limit_note", "cpu_note"):
        pass
    for k, v in (("name", a.name), ("memory", a.memory), ("cpu", a.cpu), ("disk", a.disk)):
        if v:
            cfg[k] = v
    return cfg


def config_hash(cfg):
    """VM 이 따라야 할 선언의 지문. 프로비저닝 스크립트·도구 내용·규칙·버전이 바뀌면 달라진다(VM 크기는 프로비저닝과 무관해 제외)."""
    h = hashlib.sha256()
    h.update(open(cfg["provision"], "rb").read())
    td = cfg.get("tools_dir")
    if td and os.path.isdir(td):
        for f in sorted(os.listdir(td)):
            p = os.path.join(td, f)
            if os.path.isfile(p) and f in ("ws.py", "snap.py"):
                h.update(f.encode()); h.update(open(p, "rb").read())
    h.update(json.dumps({"projects": cfg.get("projects", {}), "playwright": cfg["playwright"], "user": cfg["user"], "image": cfg["image"]}, sort_keys=True).encode())
    return h.hexdigest()[:16]


def exists(name):
    return incus("info", name, check=False).returncode == 0


def getkey(name, key):
    r = incus("config", "get", name, f"{KEY_NS}.{key}", check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def setkey(name, key, val):
    incus("config", "set", name, f"{KEY_NS}.{key}={val}")


def field(name, col):
    """`incus list <이름>` 은 이름을 접두·정규식으로 해석해 `qa-desktop-test` 같은 다른 VM 까지 잡는다 → 정확 일치(^이름$)로 한 칸만 읽는다."""
    r = incus("list", f"^{name}$", "-c", col, "--format", "csv", check=False)
    return r.stdout.strip().splitlines()[0].strip() if r.returncode == 0 and r.stdout.strip() else ""


def ip_of(name):
    return field(name, "4").split(" ")[0]


def running(name):
    return field(name, "s") == "RUNNING"


def wait_agent(name, secs=420):
    t0 = time.time()
    while time.time() - t0 < secs:
        if incus("exec", name, "--", "true", check=False).returncode == 0:
            return
        time.sleep(5)
    sys.exit(f"{name}: incus 에이전트가 {secs}초 안에 응답하지 않는다(VM 이 부팅하지 못했을 수 있다: incus console {name} --type=vga)")


def ensure_key(cfg):
    key = os.path.expanduser(cfg["ssh_key"])
    if not os.path.exists(key):
        os.makedirs(os.path.dirname(key), mode=0o700, exist_ok=True)
        log(f"접속 키가 없어 만든다: {key}")
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"qa-desktop-ctl@{os.uname().nodename}", "-f", key)
    return open(key + ".pub").read().strip()


def ensure_images_remote():
    r = incus("remote", "list", "--format=csv", check=False)
    if not any(l.split(",")[0].strip() == "images" for l in r.stdout.splitlines()):
        incus("remote", "add", "images", "https://images.linuxcontainers.org", "--protocol=simplestreams", "--public")


def mem_available_gib():
    try:
        for l in open("/proc/meminfo"):
            if l.startswith("MemAvailable:"):
                return int(l.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return None


def provision(cfg, pub, base_snapshot=False):
    name = cfg["name"]
    log(f"{name}: 프로비저닝 시작(처음이면 4~5분, 재실행은 약 1분)")
    td = cfg.get("tools_dir")
    envs = ["--env", f"QA_USER={cfg['user']}", "--env", f"QA_PUBKEY={pub}", "--env", f"QA_PLAYWRIGHT={cfg['playwright']}",
            "--env", "QA_PROJECTS=" + " ".join(f"{n}:{d}" for n, d in sorted(cfg.get("projects", {}).items()))]
    if td and os.path.isdir(td):
        incus("exec", name, "--", "mkdir", "-p", "/opt/qa-tools-src")
        for f in ("ws.py", "snap.py"):
            if os.path.exists(os.path.join(td, f)):
                incus("file", "push", os.path.join(td, f), f"{name}/opt/qa-tools-src/{f}")
        envs += ["--env", "QA_TOOLS_DIR=/opt/qa-tools-src"]
    with open(cfg["provision"]) as f:
        r = subprocess.run(["incus", "exec", name, *envs, "--", "bash", "-s"], stdin=f)
    if r.returncode != 0:
        sys.exit(f"프로비저닝 실패(rc={r.returncode}) — VM 은 남겨 둔다. 원인을 고친 뒤 `qa-desktop-ctl --name {name} ensure` 로 이어서 한다.")
    setkey(name, "provisioned", config_hash(cfg))
    setkey(name, "state", "ready")
    if base_snapshot:
        base_snapshot_offline(name)
    else:
        log(f"{name}: 프로비저닝 완료(쓰고 있던 VM 이라 끄지 않는다 — 기준 스냅샷이 필요하면 `qa-desktop-ctl snapshot <이름>`)")


def base_snapshot_offline(name):
    """최초 생성 직후의 기준 스냅샷. 실행 중인 VM 의 스냅샷은 게스트 파일시스템 동결을 기다리는데 프로비저닝 직후에는 수 분씩 막히는 것을 재현했다(수동 재시도는 0.16초).
    그래서 이때만 VM 을 잠깐 끄고 오프라인 스냅샷을 만든 뒤 다시 켠다(아직 아무도 쓰지 않는 새 VM 이라 안전하다)."""
    snap = "provisioned-" + time.strftime("%Y%m%d-%H%M")
    log(f"{name}: 기준 스냅샷을 위해 VM 을 잠깐 껐다 켠다")
    t = time.time()
    if incus("stop", name, "--timeout", "90", check=False).returncode != 0:
        log("정상 종료가 90초 안에 안 끝나 강제 종료")
        incus("stop", name, "--force", check=False)
    log(f"  정지 {time.time() - t:.0f}초")
    t = time.time()
    r = incus("snapshot", "create", name, snap, check=False)
    log(f"  스냅샷 {time.time() - t:.0f}초")
    t = time.time()
    incus("start", name)
    wait_agent(name, 180)
    log(f"  기동·에이전트 {time.time() - t:.0f}초")
    log(f"{name}: 프로비저닝 완료 · " + (f"스냅샷 {snap}" if r.returncode == 0 else f"스냅샷 실패: {(r.stderr or r.stdout).strip()[-120:]}"))


def cmd_ensure(a):
    cfg = load_config(a)
    name = cfg["name"]
    if incus("list", "-c", "n", "--format", "csv", check=False).returncode != 0:
        log("incus 데몬에 닿지 않는다(아직 부팅 중이거나 incus 가 꺼져 있다)")
        return 3
    if exists(name):
        state, prov = getkey(name, "state"), getkey(name, "provisioned")
        if state == "creating":
            log(f"{name}: 생성 도중 멈춘 VM — 이어서 프로비저닝한다")
            if not running(name):
                incus("start", name)
            wait_agent(name)
            provision(cfg, ensure_key(cfg), base_snapshot=True)
            return 0
        if not state and not prov:
            log(f"{name}: 이미 있는 VM — 건드리지 않는다(이 도구로 만든 표식이 없는 기존 VM 을 채택). 선언을 적용하려면 `qa-desktop-ctl provision` 을 직접 실행")
            return 0
        if prov != config_hash(cfg):
            log(f"{name}: 선언이 바뀌었다(VM {prov} ≠ 선언 {config_hash(cfg)}) — 반영하려면 `qa-desktop-ctl --name {name} provision`")
        else:
            log(f"{name}: 선언대로 준비돼 있다")
        return 0

    avail = mem_available_gib()
    if avail is not None and avail < 3:
        log(f"경고: 호스트 사용 가능 메모리가 {avail:.1f}GiB 로 적다(VM 한도 {cfg['memory']}) — 다른 VM 이 많이 떠 있으면 느려지거나 OOM 이 날 수 있다")
    pub = ensure_key(cfg)
    ensure_images_remote()
    log(f"{name}: 생성 시작 — 이미지 {cfg['image']}(처음이면 1.4GB 내려받기), {cfg['cpu']}CPU/{cfg['memory']}/{cfg['disk']}")
    incus("launch", cfg["image"], name, "--vm", "-c", f"limits.cpu={cfg['cpu']}", "-c", f"limits.memory={cfg['memory']}",
          "-c", "security.secureboot=false", "-c", "raw.qemu=-cpu host", "-c", f"{KEY_NS}.state=creating", "-d", f"root,size={cfg['disk']}")
    wait_agent(name)
    provision(cfg, pub, base_snapshot=True)
    log(f"{name}: 준비됨 — ssh -i {cfg['ssh_key']} {cfg['user']}@{ip_of(name)}")
    return 0


def cmd_create(a):
    cfg = load_config(a)
    if exists(cfg["name"]):
        sys.exit(f"{cfg['name']} 은(는) 이미 있다(`ensure`/`provision` 을 쓴다)")
    return cmd_ensure(a)


def cmd_provision(a):
    cfg = load_config(a)
    name = cfg["name"]
    if not exists(name):
        sys.exit(f"{name} 이(가) 없다(`ensure`)")
    legacy = not getkey(name, "state")
    if legacy and not a.yes:   # 보호 확인을 에이전트 대기보다 먼저 한다
        sys.exit(f"{name} 은(는) 이 도구로 만든 VM 이 아니다. 프로비저닝은 사용자 이름 변경·GDM 재시작·dconf·패키지를 건드린다 — 변경 전에 스냅샷을 만들고 그래도 진행하려면 --yes")
    if not running(name):
        incus("start", name)
    try:
        wait_agent(name, secs=90 if legacy else 420)
    except SystemExit:
        if legacy:
            sys.exit(f"{name} 에는 incus 에이전트가 없어 `incus exec` 프로비저닝을 할 수 없다(직접 만든 기존 VM 에서 흔하다). 이 VM 은 채택만 하고, 필요하면 새 VM 을 만들어 옮긴다")
        raise
    provision(cfg, ensure_key(cfg))
    return 0


def cmd_status(a):
    cfg = load_config(a)
    name = cfg["name"]
    if not exists(name):
        print(f"{name}: 없음 — `qa-desktop-ctl ensure` 로 만든다")
        return 1
    st = field(name, "s")
    state, prov = getkey(name, "state"), getkey(name, "provisioned")
    print(f"{name}: {st}  IP {ip_of(name) or '-'}  표식 state={state or '(없음: 기존 VM)'}")
    if prov:
        print(f"선언 일치: {'예' if prov == config_hash(cfg) else '아니오(선언이 바뀜 — provision 으로 반영)'}  (VM {prov} / 선언 {config_hash(cfg)})")
    ip = ip_of(name)
    key = os.path.expanduser(cfg["ssh_key"])
    if ip and os.path.exists(key):
        r = run("ssh", "-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                f"{cfg['user']}@{ip}", "echo ok", check=False)
        print("ssh 접속:", "ok" if r.stdout.strip() == "ok" else "실패")
    print("스냅샷:", incus("snapshot", "list", name, "-c", "n", "--format", "csv", check=False).stdout.strip().replace("\n", ", ") or "없음")
    return 0


def cmd_snapshot(a):
    cfg = load_config(a)
    incus("snapshot", "create", cfg["name"], a.snap)
    print(f"스냅샷 {a.snap} 생성")
    return 0


def cmd_destroy(a):
    cfg = load_config(a)
    if not a.yes:
        sys.exit(f"{cfg['name']} 을(를) 삭제한다(되돌릴 수 없음). 진행하려면 --yes")
    incus("delete", cfg["name"], "--force")
    print(f"{cfg['name']} 삭제됨")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config"); ap.add_argument("--name"); ap.add_argument("--memory"); ap.add_argument("--cpu"); ap.add_argument("--disk")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n, f in (("ensure", cmd_ensure), ("create", cmd_create), ("status", cmd_status)):
        sub.add_parser(n).set_defaults(f=f)
    p = sub.add_parser("provision"); p.add_argument("--yes", action="store_true"); p.set_defaults(f=cmd_provision)
    p = sub.add_parser("snapshot"); p.add_argument("snap"); p.set_defaults(f=cmd_snapshot)
    p = sub.add_parser("destroy"); p.add_argument("--yes", action="store_true"); p.set_defaults(f=cmd_destroy)
    a = ap.parse_args()
    lock = open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "qa-desktop-ctl.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("다른 qa-desktop-ctl 이 실행 중이다")
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
