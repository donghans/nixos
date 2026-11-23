#!/usr/bin/env python3
"""sbox 도구 층 엔진(plan dev-sandbox-pilot §29·§29-3, 체크리스트 S5·S34·S46).

도구마다 코드를 짜지 않고 `core/sbox/tools.toml`(카탈로그)에 「어디서 받고·무엇으로 검증하고·어떻게 푸는가」를 선언한다.
엔진은 호스트에서 공식 배포 파일을 받아 **체크섬(필요하면 GPG 서명까지) 검증** 후 `~/.cache/sbox/tools/<도구>/<버전>/` 에 풀어 쓰기 권한을 뺀다.
컨테이너는 그 폴더를 읽기 전용 디스크 장치로만 `/opt/tools/<도구>/<버전>` 에 받는다(컨테이너가 직접 내려받지 않음).

역할별 버전 정책(사용자 방침 2026-11-22):
  re(실행환경)  버전 고정 — 매니페스트 [resolved] 에 처음 풀린 정확한 버전을 기록, --update 로만 다시 해석
  de(개발환경)  항상 최신 — 해석 결과를 고정하지 않고, 새 버전을 받으면 쓰이지 않는 옛 버전은 `prune` 으로 정리

서브명령(표준출력은 기계가 읽는 한 줄 또는 JSON):
  catalog                      카탈로그의 도구·역할·설명(JSON)
  resolve TOOL [SPEC]          SPEC(22, 22.11, 22.11.0, latest, stable, lts) → 정확한 버전(de 는 SPEC 생략 시 latest).
                               움직이는 스펙(latest·lts·stable·메이저·메이저.마이너)은 공개된 지 SBOX_TOOLS_MIN_AGE_DAYS(기본 7, 0=끔)일 미만 버전을 건너뛴다(쿨다운, S55) —
                               정확한 X.Y.Z 와 Python(pbs)·Claude 채널에는 적용 안 함
  fetch TOOL VERSION           내려받기·검증·풀기 → 풀린 폴더 경로
  links TOOL                   컨테이너 /usr/local/bin 에 만들 링크(이름 → 폴더 안 상대 경로, JSON)
  prune TOOL [--keep V]        표준입력으로 받은 「쓰이는 폴더 경로」 목록에 없는 옛 버전을 지움(--keep 은 남길 버전) → 지운 버전 목록
  probe [--label L] [--out F]  이 망에서 신뢰 출발점 URL 들(채널·인덱스·서명 키·키 출처)의 본문 해시와 TLS 인증서를 기록(JSON 파일) — probe.py
  crosscheck F1 F2 …           여러 망(집 유선·핫스팟·클라우드)에서 만든 probe 결과를 비교 — 본문이 다르면 mismatch(종료코드 1)
  crosscheck-run [VANTAGE…]    ~/.config/sbox/crosscheck.toml 의 vantage(local·ssh·manual)별로 probe 를 실행·비교하고 상태에 기록
  ct-check                     CT 로그(Cert Spotter)로 공식 배포 호스트의 인증서 발급 이력을 보고 처음 보는 발급 CA 가 나오면 경고
  crosscheck-status            waybar custom 모듈용 JSON(주기가 지나면 due, 불일치·경고가 있으면 alert, 정상이면 빈 텍스트)
  periodic [--force]           주기 점검 한 번(타이머가 매일 호출): 각 점검이 자기 주기가 지났을 때만 실행 — ct-check 매주 · pincheck 매월 · crosscheck-run 은 crosscheck.toml 의 interval
  pincheck [TOOL]              서명 키 지문이 독립된 출처(키 파일·키 서버·과거 웹 아카이브·지문 목록)에서도 확인되는지 점검(JSON, 실패 시 종료코드 1). `apt-key:docker` 도 포함
  infer REPO                   프로젝트 파일(.nvmrc·package.json engines·go.mod)에서 버전 추론 → JSON
  effective MANIFEST           매니페스트의 [override] 가 [inferred] 를 덮은 최종 도구 표 → JSON
  plan [--repo DIR] [--manifest FILE] [--update] [--tool T=SPEC ...]
                               매니페스트를 만들거나 갱신하고, re 도구는 정확한 버전을 [resolved] 에 고정해 JSON 으로 낸다
                               (이미 고정된 버전은 스펙이 그대로면 재사용 — 새 패치로 조용히 바뀌지 않음. --update 로만 다시 해석)

검증: 체크섬 출처(HTTPS)와 받은 파일을 대조하고, 처음 본 (도구, 버전, 파일)의 해시를 잠금 파일(`~/.config/sbox/tools.lock`)에 적는다(TOFU).
이후엔 잠금 값과 다르면 거부한다. 카탈로그에 서명(gpg-detached)이 선언돼 있으면 체크섬 문서를 gpg 로 검증하고 주 키 지문이 선언값과 같아야 통과한다.
"""
import calendar
import email.utils
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.parse
import urllib.request

CACHE = os.path.expanduser(os.environ.get("SBOX_TOOLS_CACHE", "~/.cache/sbox/tools"))
LOCK = os.path.expanduser(os.environ.get("SBOX_TOOLS_LOCK", "~/.config/sbox/tools.lock"))
CATALOG = os.environ.get("SBOX_TOOLS_CATALOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools.toml"))
NODE_INDEX = "https://nodejs.org/dist/index.json"
GO_JSON = "https://go.dev/dl/?mode=json&include=all"
EXACT = re.compile(r"\d+\.\d+(\.\d+)?")


def fail(msg):
    print(f"sbox-tools: {msg}", file=sys.stderr)
    sys.exit(1)


def http(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sbox-tools/1.0"})  # 일반 클라이언트 이름(일부 사이트는 기본 파이썬 UA 를 막음)
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 — 카탈로그가 고정한 https 주소
        return r.read()


def _load_catalog():
    with open(CATALOG, "rb") as f:
        return tomllib.load(f)


def catalog():
    """도구 목록. `[apt-key.*]`(apt 저장소 서명 키 — 도구 층이 아니라 dockerctl 이 쓴다)는 도구가 아니므로 뺀다."""
    return {k: v for k, v in _load_catalog().items() if k != "apt-key"}


def aptkeys():
    return _load_catalog().get("apt-key") or {}


def tool(name):
    t = catalog().get(name)
    if not isinstance(t, dict):
        fail(f"카탈로그에 없는 도구: {name} (있는 도구: {', '.join(catalog())})")
    return t


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


# ---------- 해석(resolver) ----------
# ---------- 릴리스 최소 연령(쿨다운, S55) ----------
def _min_age_days():
    try:
        return float(os.environ.get("SBOX_TOOLS_MIN_AGE_DAYS", "7"))
    except ValueError:
        fail("SBOX_TOOLS_MIN_AGE_DAYS 는 숫자(일)여야 합니다 — 0 이면 쿨다운을 끕니다")


def _epoch(s):
    """YYYY-MM-DD · ISO(2026-11-17T09:57:55Z) · YYYYMMDD(pbs 태그) · HTTP 날짜(Last-Modified) → 에포크 초. 읽지 못하면 None."""
    if not s:
        return None
    s = str(s).strip()
    try:
        if re.fullmatch(r"\d{8}", s):
            return calendar.timegm(time.strptime(s, "%Y%m%d"))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s[:10]) and (len(s) == 10 or s[10] in "T "):
            return calendar.timegm(time.strptime(s[:19] if len(s) >= 19 else s[:10], "%Y-%m-%dT%H:%M:%S" if len(s) >= 19 and s[10] == "T" else "%Y-%m-%d"))
        return email.utils.parsedate_to_datetime(s).timestamp()
    except (ValueError, TypeError):
        return None


def _is_moving(spec):
    """움직이는 가리킴(latest·lts·stable·메이저·메이저.마이너)인가 — 정확한 X.Y.Z 는 사용자가 직접 고른 것이라 쿨다운 대상이 아니다."""
    return spec in ("latest", "lts", "stable") or bool(re.fullmatch(r"\d+(\.\d+)?", spec))


def pick_aged(cands, min_days, now=None):
    """cands: [(버전, 공개 에포크 초 또는 None)] 를 **새것부터** 훑는 이터러블(게으르게 소비). 공개된 지 min_days 일 이상인 첫 후보를 고른다.
    반환 (버전 또는 None, 알림 문구 리스트, 건너뛴 더 새 버전들). 날짜를 못 읽은 후보는 막지 않고(안 보이는 안전이 되지 않게) 「날짜 불명 — 쿨다운 미적용」으로 알린다. min_days<=0 이면 첫 후보."""
    now = time.time() if now is None else now
    notes, first, skipped = [], None, []
    for v, ts in cands:
        if first is None:
            first = v
        if min_days <= 0:
            return v, notes, []
        if ts is None:
            return v, notes + [f"{v}: 공개 날짜를 읽지 못해 쿨다운을 적용하지 못했습니다(날짜 불명)"], [sv for sv, _ in skipped]
        age = (now - ts) / 86400
        if age >= min_days:
            if skipped:
                notes.append("쿨다운 " + f"{min_days:g}일: " + ", ".join(f"{sv}(공개 {sa:.1f}일)" for sv, sa in skipped) + f" 는 건너뛰고 {v}(공개 {age:.1f}일) 를 고릅니다")
            return v, notes, [sv for sv, _ in skipped]
        skipped.append((v, age))
    return None, notes + ([f"쿨다운 {min_days:g}일을 넘긴 후보가 없습니다(가장 새 {first})"] if first else ["후보가 없습니다"]), []


def _node_cands(spec):
    for e in json.loads(http(NODE_INDEX)):  # 최신순
        v = e["version"].lstrip("v")
        if not EXACT.fullmatch(v):
            continue  # alpha·rc 제외
        if (spec == "lts" and e.get("lts")) or (spec != "lts" and (v == spec or v.startswith(spec + "."))):
            yield v, _epoch(e.get("date"))


def _github_cands(r, spec):
    pre = r.get("tag_prefix", "")
    items = []
    for x in json.loads(http(f"https://api.github.com/repos/{r['repo']}/releases?per_page=100")):
        v = x["tag_name"].removeprefix(pre)
        if x.get("prerelease") or x.get("draft") or not x["tag_name"].startswith(pre) or not re.fullmatch(r"\d+\.\d+\.\d+", v):
            continue
        if spec == "latest" or v == spec or v.startswith(spec + "."):
            items.append((v, _epoch(x.get("published_at"))))
    return sorted(items, key=lambda c: vtuple(c[0]), reverse=True)


def _head_date(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "sbox-tools/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — 카탈로그가 고정한 https 주소
            return _epoch(r.headers.get("Last-Modified"))
    except OSError:
        return None


def _go_cands(spec):
    for e in _go_entries():  # 최신순 — go.dev JSON 에는 날짜가 없어 아카이브의 Last-Modified 를 쓴다(게으르게: 고를 때까지만 조회)
        v = e["version"].removeprefix("go")
        if spec == "latest" or v == spec or v.startswith(spec + "."):
            yield v, _head_date(f"https://dl.google.com/go/go{v}.linux-amd64.tar.gz")


def _rust_cands(spec):
    """stable → 채널 문서의 최신 + 한 마이너씩 낮춘 문서들(최대 4개), X.Y → 그 문서 하나. 문서의 date 가 공개일."""
    def doc(name):
        try:
            d = tomllib.loads(http(f"https://static.rust-lang.org/dist/{name}").decode())
        except OSError:
            return None
        return d["pkg"]["rust"]["version"].split()[0], _epoch(d.get("date"))
    if re.fullmatch(r"\d+\.\d+", spec):
        c = doc(f"channel-rust-{spec}.toml")
        if c:
            yield c
        return
    first = doc("channel-rust-stable.toml")
    if not first:
        return
    yield first
    major, minor = (int(x) for x in first[0].split(".")[:2])
    for m in range(minor - 1, max(minor - 4, -1), -1):
        c = doc(f"channel-rust-{major}.{m}.toml")
        if c:
            yield c


COOLDOWN_TYPES = ("node-index", "go-json", "github-release", "rust-channel")   # pbs(Python)는 제외 — 같은 버전이 여러 날짜 태그에 있고 fetch 가 가장 새 태그를 다시 고르므로 버전만 골라서는 쿨다운이 안 된다(한계, S55)


def _cooldown_resolve(name, r, typ, spec):
    cands = {"node-index": lambda: _node_cands(spec), "go-json": lambda: _go_cands(spec), "github-release": lambda: _github_cands(r, spec),
             "rust-channel": lambda: _rust_cands(spec)}[typ]()
    v, notes, skipped = pick_aged(cands, _min_age_days())
    for n in notes:
        print(f"sbox-tools: {name} {spec}: {n}", file=sys.stderr)
    if v is None:
        fail(f"{name} {spec}: 공개된 지 {_min_age_days():g}일 이상인 버전이 없습니다 — 정확한 X.Y.Z 로 지정하거나 SBOX_TOOLS_MIN_AGE_DAYS=0 으로 끄세요")
    return v, skipped


def resolve(name, spec=None):
    t = tool(name)
    r = t.get("resolver") or {}
    typ = r.get("type")
    if not spec:
        spec = r.get("default") if t.get("role") == "de" else None
        if not spec:
            fail(f"{name}: 스펙이 필요합니다(re 도구는 생략할 수 없음)")
    spec = str(spec).lstrip("v")
    cooled = []   # 쿨다운이 건너뛴 더 새 버전들 — 롤백 방지가 「이전에 본 버전이 낮아진 이유」로 설명받는다
    if typ in COOLDOWN_TYPES and _is_moving(spec) and _min_age_days() > 0:
        v, cooled = _cooldown_resolve(name, r, typ, spec)
    elif typ == "node-index":
        v = _node_resolve(spec)
    elif typ == "go-json":
        v = _go_resolve(spec)
    elif typ == "github-release":
        v = _github_resolve(r, spec)
    elif typ == "rust-channel":
        v = _rust_resolve(spec)
    elif typ == "pbs":
        v = _pbs_resolve(spec)
    elif typ == "channel-file" and spec in r.get("channels", []):
        v = http(r["url"].format(channel=spec)).decode().strip()
    else:
        v = spec
    if not EXACT.fullmatch(v):
        fail(f"{name}: 해석한 버전이 올바르지 않습니다: {spec} → {v!r}")
    _rollback_guard(name, spec, v, moving=(typ == "channel-file" and spec in r.get("channels", [])) or spec in ("latest", "lts", "stable"), explained=cooled)
    mn = t.get("min_version")
    if mn and vtuple(v) < vtuple(mn):
        fail(f"{name} {v} 는 최소 버전 {mn} 보다 낮습니다(서명 없는 옛 릴리스 등) — 거부")
    return v


def _rollback_guard(name, spec, v, moving, explained=()):
    """움직이는 가리킴(latest·lts·채널 이름)이 **본 적 있는 최고 버전보다 낮은 버전**을 가리키면 거부한다(롤백·다운그레이드 방어, S47).
    채널 파일은 서명이 없어 공격자가 옛 서명 릴리스를 가리키게 해도 서명 검증은 통과하기 때문이다. 공급자의 정상 롤백이면
    SBOX_TOOLS_ALLOW_DOWNGRADE=1 로 한 번 허용한다. 고정 버전(정확한 X.Y.Z 스펙)에는 적용하지 않는다."""
    if not moving:
        return
    key = f"_max/{name}/{spec}"
    lock = load_lock()
    prev = lock.get(key)
    if prev and vtuple(v) < vtuple(prev) and prev in explained:
        return  # 이전에 본 더 높은 버전은 이번에 쿨다운이 건너뛴 후보다 — 롤백이 아니라 쿨다운이 낮춘 것(기준선은 그대로 둔다)
    if prev and vtuple(v) < vtuple(prev) and os.environ.get("SBOX_TOOLS_ALLOW_DOWNGRADE") != "1":
        fail(f"{name} {spec} 가 이전에 본 {prev} 보다 낮은 {v} 를 가리킵니다 — 롤백 공격이거나 공급자의 정상 롤백입니다. "
             f"확인 뒤 SBOX_TOOLS_ALLOW_DOWNGRADE=1 로 다시 실행하세요")
    # 새 최고이거나, 사용자가 낮아진 것을 허용한 경우(그 값을 새 기준선으로 — 매번 환경변수를 줄 필요가 없게)
    if not prev or vtuple(v) > vtuple(prev) or (vtuple(v) < vtuple(prev) and os.environ.get("SBOX_TOOLS_ALLOW_DOWNGRADE") == "1"):
        lock[key] = v
        save_lock(lock)


def _node_resolve(spec):
    idx = json.loads(http(NODE_INDEX))
    if spec == "lts":
        for e in idx:
            if e.get("lts"):
                return e["version"].lstrip("v")
        fail("Node LTS 를 찾지 못했습니다")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", spec):
        fail(f"node 스펙 표기가 올바르지 않습니다: {spec}")
    for e in idx:  # 최신순
        v = e["version"].lstrip("v")
        if v == spec or v.startswith(spec + "."):
            return v
    fail(f"node {spec} 에 맞는 버전이 없습니다")


def _github_resolve(r, spec):
    """GitHub 릴리스 목록(정식만)에서 스펙에 맞는 최신 버전. tag_prefix(예: v)는 떼고 돌려준다. 인증 없는 API(시간당 60회)."""
    pre = r.get("tag_prefix", "")
    rels = json.loads(http(f"https://api.github.com/repos/{r['repo']}/releases?per_page=100"))
    vers = [x["tag_name"].removeprefix(pre) for x in rels if not x.get("prerelease") and not x.get("draft") and x["tag_name"].startswith(pre)]
    vers = [v for v in vers if re.fullmatch(r"\d+\.\d+\.\d+", v)]
    if spec == "latest":
        if not vers:
            fail(f"{r['repo']}: 정식 릴리스를 찾지 못했습니다")
        return max(vers, key=vtuple)
    ok = [v for v in vers if v == spec or v.startswith(spec + ".")]
    if not ok:
        fail(f"{r['repo']}: {spec} 에 맞는 릴리스가 최근 100개 안에 없습니다(오래된 버전은 정확한 X.Y.Z 로 지정)")
    return max(ok, key=vtuple)


def _rust_resolve(spec):
    """stable·X.Y(최신 패치)·X.Y.Z → 정확한 Rust 버전. 채널 문서(서명 검증은 fetch 에서)의 [pkg.rust] version 을 읽는다."""
    if re.fullmatch(r"\d+\.\d+\.\d+", spec):
        return spec
    if spec == "stable":
        doc = "channel-rust-stable.toml"
    elif re.fullmatch(r"\d+\.\d+", spec):
        doc = f"channel-rust-{spec}.toml"
    else:
        fail(f"rust 스펙은 stable·X.Y·X.Y.Z 만 지원합니다(nightly·beta 제외): {spec}")
    d = tomllib.loads(http(f"https://static.rust-lang.org/dist/{doc}").decode())
    return d["pkg"]["rust"]["version"].split()[0]


_PBS_SUMS = {}


def _pbs_tags():
    rels = json.loads(http("https://api.github.com/repos/astral-sh/python-build-standalone/releases?per_page=12"))
    return [x["tag_name"] for x in rels if not x.get("prerelease") and not x.get("draft")]


def _pbs_versions(tag):
    if tag not in _PBS_SUMS:
        _PBS_SUMS[tag] = http(f"https://github.com/astral-sh/python-build-standalone/releases/download/{tag}/SHA256SUMS").decode()
    pat = re.compile(r"cpython-(\d+\.\d+\.\d+)\+%s-x86_64-unknown-linux-gnu-install_only\.tar\.gz$" % re.escape(tag), re.M)
    return sorted({m.group(1) for m in pat.finditer(_PBS_SUMS[tag])}, key=vtuple)


def _pbs_resolve(spec):
    """가장 새 릴리스(날짜 태그)에 들어 있는 install_only 빌드 중 스펙(latest·3.12·3.12.16)에 맞는 최신 버전."""
    tag = _pbs_tags()[0]
    vers = _pbs_versions(tag)
    if spec == "latest":
        ok = vers
    else:
        ok = [v for v in vers if v == spec or v.startswith(spec + ".")]
    if not ok:
        fail(f"python {spec} 에 맞는 빌드가 최신 릴리스({tag})에 없습니다 — 오래된 패치는 정확한 X.Y.Z 로 지정(최근 12개 릴리스 안에서 찾음)")
    return ok[-1]


def _pbs_tag(version):
    for tag in _pbs_tags():
        if version in _pbs_versions(tag):
            return tag
    fail(f"python {version} 빌드가 최근 12개 릴리스에 없습니다")


def _extra_fmt(t, version):
    if (t.get("resolver") or {}).get("type") == "pbs":
        return {"tag": _pbs_tag(version)}
    return {}


def _go_entries():
    return [e for e in json.loads(http(GO_JSON)) if e.get("stable")]


def _go_resolve(spec):
    es = _go_entries()
    if spec == "latest":
        return es[0]["version"].removeprefix("go")
    for e in es:  # 최신순
        v = e["version"].removeprefix("go")
        if v == spec or v.startswith(spec + "."):
            return v
    fail(f"go {spec} 에 맞는 안정 버전이 없습니다")


# ---------- 잠금(TOFU) ----------
def load_lock():
    try:
        with open(LOCK, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_lock(d):
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, sort_keys=True)


# ---------- 서명(gpg) ----------
def gpg_cmd():
    """gpg 가 호스트에 없으면 일회성으로 nix shell nixpkgs#gnupg 를 쓴다(전역 지침: 임의 설치 금지)."""
    if shutil.which("gpg"):
        return ["gpg"]
    if shutil.which("nix"):
        return ["nix", "shell", "nixpkgs#gnupg", "-c", "gpg"]
    fail("gpg 도 nix 도 없습니다")


def _norm_fprs(sg):
    f = sg.get("fingerprints") or ([sg["fingerprint"]] if sg.get("fingerprint") else [])
    if not f:
        fail("서명 선언에 fingerprint(s) 가 없습니다")
    return [x.replace(" ", "").upper() for x in f]


def verify_gpg(doc_path, sig_bytes, sg, workdir):
    """분리 서명 검증. 서명 주 키 지문이 선언한 허용 목록(fingerprints) 중 하나여야 통과한다(VALIDSIG 의 마지막 필드).
    공개키는 key_url(s) 에서 받거나(고정 키), key_lookup 템플릿으로 **서명에 적힌 서명자 키**만 받아 온다(허용 지문이 많을 때)."""
    allowed = set(_norm_fprs(sg))
    sigp = os.path.join(workdir, "doc.sig")
    open(sigp, "wb").write(sig_bytes)
    home = os.path.join(workdir, "gnupg")
    os.makedirs(home, mode=0o700, exist_ok=True)
    g = gpg_cmd() + ["--homedir", home, "--batch", "--no-tty"]
    keys = []
    for u in (sg.get("key_urls") or ([sg["key_url"]] if sg.get("key_url") else [])):
        keys.append(http(u))
    if sg.get("key_lookup"):
        r = subprocess.run(g + ["--list-packets", sigp], capture_output=True, text=True)
        m = re.search(r"issuer fpr v\d (\w{40})", r.stdout + r.stderr)
        if not m:
            fail("서명에서 서명자 지문을 읽지 못했습니다")
        keys.append(http(sg["key_lookup"].format(fingerprint=m.group(1))))
    if not keys:
        fail("공개키 출처(key_url·key_lookup)가 선언돼 있지 않습니다")
    for i, k in enumerate(keys):
        kp = os.path.join(workdir, f"key{i}.asc")
        open(kp, "wb").write(k)
        r = subprocess.run(g + ["--import", kp], capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"공개키 가져오기 실패: {r.stderr.strip()[:200]}")
    r = subprocess.run(g + ["--status-fd", "1", "--verify", sigp, doc_path], capture_output=True, text=True)
    prim = None
    for ln in r.stdout.splitlines():
        if ln.startswith("[GNUPG:] VALIDSIG"):
            prim = ln.split()[-1].upper()
        if ln.startswith(("[GNUPG:] BADSIG", "[GNUPG:] ERRSIG")):
            fail(f"서명 검증 실패: {ln}")
    if prim not in allowed:
        fail(f"서명 주 키 지문이 허용 목록에 없습니다(받은 {prim}, 허용 {len(allowed)}개 중) — 중단")


def cosign_cmd():
    if shutil.which("cosign"):
        return ["cosign"]
    if shutil.which("nix"):
        return ["nix", "shell", "nixpkgs#cosign", "-c", "cosign"]
    fail("cosign 도 nix 도 없습니다")


def verify_sigstore(art_path, sha, version, sg, workdir):
    """Sigstore 증명(in-toto) 검증: 번들을 받아 cosign 이 인증서 신원(OIDC 발급자·워크플로 SAN 정규식)과 투명성 로그 포함, 산출물 해시 일치를 확인한다."""
    bpath = os.path.join(workdir, "bundle.json")
    src = sg.get("bundle_from", "asset")
    if src == "asset":
        open(bpath, "wb").write(http(sg["bundle_url"].format(version=version)))
    elif src == "github-attestations":
        d = json.loads(http(f"https://api.github.com/repos/{sg['repo']}/attestations/sha256:{sha}"))
        want = sg.get("predicate_type", "https://slsa.dev/provenance/v1")
        pick = None
        for x in d.get("attestations", []):
            pl = json.loads(__import__("base64").b64decode(x["bundle"]["dsseEnvelope"]["payload"]))
            if pl.get("predicateType") == want:
                pick = x["bundle"]
                break
        if not pick:
            fail(f"GitHub 증명에 {want} 종류가 없습니다({sg['repo']}, {sha[:12]})")
        json.dump(pick, open(bpath, "w"))
    else:
        fail(f"알 수 없는 번들 출처: {src}")
    cmd = cosign_cmd() + ["verify-blob-attestation", "--bundle", bpath, "--new-bundle-format", "--type", sg.get("predicate_type_cosign", "slsaprovenance1"),
                          "--certificate-oidc-issuer", sg["issuer"], "--certificate-identity-regexp", sg["identity_regexp"], art_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"Sigstore 검증 실패: {(r.stderr or r.stdout).strip().splitlines()[-1][:300]}")


# ---------- 체크섬 출처 ----------
def _one_hash(name, c, version, fname_hint=None, extra=None):
    """체크섬 출처 하나에서 (해시, 파일 이름)과 원문 문서를 읽는다. 서명 검증은 호출자가 한다."""
    typ = c["type"]
    fmt = {"version": version, "file": fname_hint or "", **(extra or {})}
    if typ == "go-json":
        want_file = f"go{version}.linux-amd64.tar.gz"
        for e in json.loads(http(GO_JSON)):
            if e["version"] == f"go{version}":
                for f in e["files"]:
                    if f["filename"] == want_file and f.get("sha256"):
                        return f["sha256"], want_file, None
        fail(f"go.dev JSON 에 {want_file} 의 해시가 없습니다")
    doc = http(c["url"].format(**fmt))
    if typ == "single-hash":  # 주소가 해시 한 줄(뒤에 이름이 있어도 됨)만 돌려주는 형식
        return doc.decode().split()[0], fname_hint, doc
    if typ == "sums-file":
        fname = c["name"].format(**fmt)
        for ln in doc.decode().splitlines():
            parts = ln.split(None, 1)
            if len(parts) == 2 and parts[1].strip().lstrip("*") == fname:  # 「해시  이름」·「해시 *이름」 둘 다
                return parts[0], fname, doc
        fail(f"체크섬 문서에 {fname} 이 없습니다")
    if typ == "json-manifest":
        cur = tomllib.loads(doc.decode()) if c.get("format") == "toml" else json.loads(doc)
        if cur.get("version") not in (None, version):
            fail(f"manifest 버전 불일치: {cur.get('version')} ≠ {version}")
        for k in c["path"].split("."):
            cur = (cur or {}).get(k)
        if not isinstance(cur, str):
            fail(f"manifest 에서 {c['path']} 를 찾지 못했습니다")
        return cur, None, doc
    fail(f"알 수 없는 체크섬 방식: {typ}")


def expected_hash(name, t, version, workdir):
    """(sha256, 산출물 파일 이름) 을 돌려준다. 서명이 target=doc 이면 체크섬 문서를 먼저 서명 검증하고,
    checksum.cross 에 선언된 다른 출처가 있으면 **모두 같은 해시여야** 한다(다채널 교차 확인)."""
    c = t["checksum"]
    sg = t.get("signature") or {"type": "none"}
    extra = _extra_fmt(t, version)
    want, fname, doc = _one_hash(name, c, version, None, extra)
    fmt = {"version": version, "file": fname or "", **extra}
    if sg["type"] == "gpg-detached" and sg.get("target", "doc") == "doc":
        dp = os.path.join(workdir, "doc")
        open(dp, "wb").write(doc if doc is not None else b"")
        verify_gpg(dp, http(sg["sig_url"].format(**fmt)), sg, workdir)
    elif sg["type"] not in ("none", "gpg-detached", "sigstore"):
        fail(f"{name}: 알 수 없는 서명 방식 {sg['type']}")
    for i, cc in enumerate(c.get("cross") or []):
        other, _, _ = _one_hash(name, cc, version, fname, extra)
        if other != want:
            fail(f"{name}: 체크섬 교차 확인 불일치(출처 0 = {want[:16]}…, 교차 {i + 1} = {other[:16]}…) — 중단")
    return want, fname


# ---------- 받기·풀기 ----------
def _make_writable_tree(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode | stat.S_IWUSR)
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)


def _make_readonly_tree(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode & ~0o222)
    os.chmod(path, os.stat(path).st_mode & ~0o222)


def fetch(name, version):
    t = tool(name)
    if not EXACT.fullmatch(version):
        fail(f"정확한 버전이 필요합니다: {version}")
    dest = os.path.join(CACHE, name, version)
    if os.path.isdir(dest) and os.listdir(dest):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(dest), prefix=".x-")
    try:
        if t["archive"]["type"] == "rust-installer":
            final = os.path.join(tmp, "final")
            _fetch_rust(name, t, version, tmp, final)
            for rel in (t.get("links") or {}).values():
                if not os.path.lexists(os.path.join(final, rel)):
                    fail(f"푼 결과에 링크 대상이 없습니다: {rel}")
            os.replace(final, dest)
            _make_readonly_tree(dest)
            return dest
        want, fname = expected_hash(name, t, version, tmp)
        if not re.fullmatch(r"[a-f0-9]{64}", want):
            fail(f"체크섬 형식이 올바르지 않습니다: {want!r}")
        url = t["url"].format(version=version, file=fname or "", **_extra_fmt(t, version))
        key = f"{name}/{version}/{os.path.basename(url)}"
        lock = load_lock()
        if key in lock and lock[key] != want:
            fail(f"잠금 해시와 공식 체크섬이 다릅니다({key}) — 중단")
        h = hashlib.sha256()
        art = os.path.join(tmp, "artifact")
        with urllib.request.urlopen(url, timeout=300) as r, open(art, "wb") as out:  # noqa: S310
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                h.update(b)
                out.write(b)
        if h.hexdigest() != want:
            fail(f"sha256 불일치: 받은 {h.hexdigest()} ≠ 공식 {want}")
        sg = t.get("signature") or {"type": "none"}
        if sg["type"] == "gpg-detached" and sg.get("target") == "artifact":
            verify_gpg(art, http(sg["sig_url"].format(version=version, file=fname or "")), sg, tmp)
        elif sg["type"] == "sigstore":
            verify_sigstore(art, want, version, sg, tmp)
        if key not in lock:
            lock[key] = want
            save_lock(lock)
        a = t["archive"]
        final = os.path.join(tmp, "final")
        if a["type"] == "tar":
            ex = os.path.join(tmp, "ex")
            with tarfile.open(art) as tf:
                tf.extractall(ex, filter="data")
            src = ex
            for _ in range(int(a.get("strip", 0))):
                kids = os.listdir(src)
                if len(kids) != 1:
                    fail("압축 파일의 맨 앞 폴더가 하나가 아닙니다")
                src = os.path.join(src, kids[0])
            os.replace(src, final)
        elif a["type"] == "binary":
            os.makedirs(final)
            os.replace(art, os.path.join(final, a["name"]))
            os.chmod(os.path.join(final, a["name"]), 0o755)
        else:
            fail(f"알 수 없는 압축 방식: {a['type']}")
        for rel in (t.get("links") or {}).values():
            if not os.path.lexists(os.path.join(final, rel)):
                fail(f"푼 결과에 링크 대상이 없습니다: {rel}")
        os.replace(final, dest)  # 폴더 이름 바꾸기는 쓰기 권한이 필요하므로 읽기 전용으로 만들기 전에
        _make_readonly_tree(dest)
    finally:
        if os.path.isdir(tmp):
            _make_writable_tree(tmp)
            shutil.rmtree(tmp, ignore_errors=True)
    return dest


def _download_hashed(url, out_path):
    h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=300) as r, open(out_path, "wb") as out:  # noqa: S310
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            h.update(b)
            out.write(b)
    return h.hexdigest()


def _fetch_rust(name, t, version, tmp, final):
    """Rust: 서명된 채널 문서(toml)의 패키지별 해시로 tar.xz 를 검증하고 각 설치기(install.sh)를 같은 prefix 로 실행한다."""
    c, sg, a = t["checksum"], t["signature"], t["archive"]
    fmt = {"version": version}
    doc = http(c["url"].format(**fmt))
    dp = os.path.join(tmp, "doc")
    open(dp, "wb").write(doc)
    verify_gpg(dp, http(sg["sig_url"].format(**fmt)), sg, tmp)
    d = tomllib.loads(doc.decode())
    if not d["pkg"]["rust"]["version"].startswith(version + " "):
        fail(f"채널 문서의 rust 버전이 다릅니다: {d['pkg']['rust']['version']} ≠ {version}")
    triple = a.get("target", "x86_64-unknown-linux-gnu")
    lock = load_lock()
    os.makedirs(final)
    for pkg in a["pkgs"]:
        ent = d["pkg"][pkg]["target"][triple]
        if not ent.get("available") or not ent.get("xz_url"):
            fail(f"채널 문서에 {pkg} ({triple}) 가 없습니다")
        url, want = ent["xz_url"], ent["xz_hash"]
        key = f"{name}/{version}/{os.path.basename(url)}"
        if key in lock and lock[key] != want:
            fail(f"잠금 해시와 서명된 채널 문서가 다릅니다({key}) — 중단")
        art = os.path.join(tmp, f"{pkg}.tar.xz")
        got = _download_hashed(url, art)
        if got != want:
            fail(f"sha256 불일치({pkg}): 받은 {got} ≠ 서명된 문서 {want}")
        if key not in lock:
            lock[key] = want
            save_lock(lock)
        ex = os.path.join(tmp, f"ex-{pkg}")
        with tarfile.open(art) as tf:
            tf.extractall(ex, filter="data")
        kids = os.listdir(ex)
        if len(kids) != 1:
            fail(f"{pkg} 압축 파일의 맨 앞 폴더가 하나가 아닙니다")
        cmd = ["sh", os.path.join(ex, kids[0], "install.sh"), f"--prefix={final}", "--disable-ldconfig"]
        wo = (a.get("without") or {}).get(pkg)
        if wo:
            cmd.append(f"--without={wo}")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"{pkg} 설치기 실패: {(r.stderr or r.stdout).strip()[-300:]}")
        os.remove(art)
        shutil.rmtree(ex, ignore_errors=True)


def _gpg_fprs(data, workdir, tag):
    p = os.path.join(workdir, f"pc-{tag}.asc")
    open(p, "wb").write(data)
    r = subprocess.run(gpg_cmd() + ["--show-keys", "--with-colons", p], capture_output=True, text=True)
    return {ln.split(":")[9].upper() for ln in r.stdout.splitlines() if ln.startswith("fpr:")}


def pincheck(only=None):
    """서명 키 지문이 **서로 독립된 출처**에서도 확인되는지 점검한다(카탈로그 signature.key_sources).
    출처 종류: url(키 파일) · keyserver(템플릿) · wayback(과거 스냅샷 — 시간차 채널) · list(지문이 적힌 텍스트·README)."""
    out = {}
    ok_all = True
    work = tempfile.mkdtemp(prefix="pincheck-")
    try:
        entries = [(n, t.get("signature") or {}) for n, t in catalog().items()]
        entries += [(f"apt-key:{n}", dict(k, type="gpg-detached")) for n, k in aptkeys().items()]   # apt 서명 키도 같은 규칙(독립 출처 N곳)으로 점검
        for name, sg in entries:
            if sg.get("type") != "gpg-detached" or (only and name != only):
                continue
            fprs = _norm_fprs(sg)
            rows = []
            for i, src in enumerate(sg.get("key_sources") or []):
                kind, label = src["type"], src.get("label", src["type"])
                found, note = set(), ""
                try:
                    if kind == "url":
                        found = _gpg_fprs(http(src["url"]), work, f"{name}{i}")
                    elif kind == "keyserver":
                        for f in fprs[:3]:
                            found |= _gpg_fprs(http(src["url"].format(fingerprint=f)), work, f"{name}{i}{f[:6]}")
                    elif kind == "wayback":
                        ts = src.get("timestamp")
                        if not ts:
                            cdx = json.loads(http("http://web.archive.org/cdx/search/cdx?url=%s&output=json&limit=1&filter=statuscode:200" % src["url"].split("://", 1)[1]))
                            if len(cdx) < 2:
                                raise RuntimeError("스냅샷 없음")
                            ts = cdx[1][1]
                        note = f"스냅샷 {ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                        found = _gpg_fprs(http(f"https://web.archive.org/web/{ts}id_/{src['url']}"), work, f"{name}{i}")
                    elif kind == "list":
                        txt = http(src["url"]).decode("utf-8", "ignore").upper().replace(" ", "")
                        found = {f for f in fprs if f in txt}
                    else:
                        raise RuntimeError(f"알 수 없는 출처 종류 {kind}")
                except Exception as e:  # 한 출처의 실패가 전체 점검을 멈추지 않게
                    note = f"실패: {str(e)[:80]}"
                rows.append({"source": label, "kind": kind, "matched": sorted(f for f in fprs if f in found), "note": note})
            need = int(sg.get("min_independent", 2))
            covered = {f: sum(1 for r in rows if f in r["matched"]) for f in fprs}
            ok = all(c >= need for c in covered.values())  # 허용 지문마다 독립 출처 need 곳 이상에서 확인돼야 통과
            ok_all &= ok
            out[name] = {"fingerprints": len(fprs), "required_independent_sources": need, "ok": ok, "sources": rows}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out, ok_all


# ---------- 망 관점(vantage) 교차 확인·CT 감시·주기 알림 ----------
STATE = os.path.expanduser(os.environ.get("SBOX_XCHECK_STATE", "~/.local/state/sbox/crosscheck.json"))
XCFG = os.path.expanduser(os.environ.get("SBOX_XCHECK_CONFIG", "~/.config/sbox/crosscheck.toml"))
RUNS = os.path.expanduser(os.environ.get("SBOX_XCHECK_RUNS", "~/.local/state/sbox/crosscheck"))
INTERVAL_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91}
PROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py")


def probe_urls():
    """카탈로그에서 「신뢰의 출발점」이 되는 공개 주소를 모은다: 버전 가리킴(채널·인덱스) · 서명 키 파일 · 키 출처. (산출물 자체는 크므로 제외)"""
    urls = []
    for name, t in catalog().items():
        r = t.get("resolver") or {}
        if r.get("type") == "channel-file":
            urls += [r["url"].format(channel=c) for c in r.get("channels", [])]
        elif r.get("type") == "node-index":
            urls.append(NODE_INDEX)
        elif r.get("type") == "go-json":
            urls.append(GO_JSON)
        elif r.get("type") == "rust-channel":
            urls.append("https://static.rust-lang.org/dist/channel-rust-stable.toml")
        sg = t.get("signature") or {}
        urls += list(sg.get("key_urls") or ([sg["key_url"]] if sg.get("key_url") else []))
        urls += [k["url"] for k in sg.get("key_sources", []) if k["type"] in ("url", "list")]
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def ct_domains():
    """CT 감시 대상 도메인: 카탈로그가 직접 접속하는 공식 배포 호스트(제3자 서비스·거대 공용 호스트는 제외)."""
    skip = {"github.com", "api.github.com", "raw.githubusercontent.com", "keyserver.ubuntu.com", "keys.openpgp.org", "web.archive.org"}
    hosts = set()
    for u in probe_urls():
        h = urllib.parse.urlsplit(u).hostname
        if h and h not in skip:
            hosts.add(h)
    hosts |= {"nodejs.org", "go.dev", "downloads.claude.ai"}
    return sorted(hosts)


def load_xcfg():
    cfg = {"interval": "monthly", "vantages": {"local": {"kind": "local"}}}
    if os.path.isfile(XCFG):
        with open(XCFG, "rb") as f:
            user = tomllib.load(f)
        cfg["interval"] = user.get("interval", cfg["interval"])
        if user.get("vantage"):
            cfg["vantages"] = user["vantage"]
    if cfg["interval"] not in INTERVAL_DAYS:
        fail(f"crosscheck.toml 의 interval 은 {'·'.join(INTERVAL_DAYS)} 중 하나여야 합니다: {cfg['interval']}")
    return cfg


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def run_probe(vantage, label):
    """한 관점에서 탐침을 실행해 결과(dict)를 돌려준다. kind: local(이 호스트의 지금 망) · ssh(원격 호스트에서 — 클라우드 인스턴스·다른 망의 PC) · manual(사람이 그 망에 접속해 직접 실행, 여기서는 건너뜀)."""
    kind = vantage.get("kind")
    urls = json.dumps(probe_urls())
    if kind == "local":
        r = subprocess.run([sys.executable, PROBE, urls, label], capture_output=True, text=True, timeout=600)
    elif kind == "ssh":
        # 탐침 스크립트를 표준입력으로 흘려 보내 원격에서 실행한다(원격에 파일을 남기지 않음). BatchMode: 암호 질문 없이 실패
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", vantage["target"], "python3", "-", urls, label],
                           stdin=open(PROBE, "rb"), capture_output=True, text=True, timeout=600)
    else:
        return None
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-200:] or f"종료코드 {r.returncode}")
    return json.loads(r.stdout)


def compare_probes(runs):
    """여러 관점의 탐침 결과를 URL 별로 비교한다. 본문 해시가 다르면 mismatch(경고), 발급 CA 가 다르면 warn, 인증서 자체만 다르면 info(CDN 은 지점마다 다른 인증서를 줄 수 있음)."""
    findings = []
    by_url = {}
    for run in runs:
        for r in run["results"]:
            by_url.setdefault(r["url"], []).append((run["label"], r))
    for url, items in by_url.items():
        ok = [(l, r) for l, r in items if "sha256" in r]
        bad = [(l, r) for l, r in items if "error" in r]
        for l, r in bad:
            findings.append({"level": "warn", "url": url, "msg": f"{l}: 접속 실패 — {r['error']}"})
        if len({r["sha256"] for _, r in ok}) > 1:
            findings.append({"level": "mismatch", "url": url, "msg": "관점마다 본문이 다름: " + ", ".join(f"{l}={r['sha256'][:10]}" for l, r in ok)})
    hosts = {}
    for run in runs:
        for h, v in run["hosts"].items():
            hosts.setdefault(h, []).append((run["label"], v.get("tls", {})))
    for h, items in hosts.items():
        issuers = {t.get("issuer") for _, t in items if t.get("issuer")}
        certs = {t.get("cert_sha256") for _, t in items if t.get("cert_sha256")}
        if len(issuers) > 1:
            findings.append({"level": "warn", "url": h, "msg": "관점마다 발급 CA 가 다름: " + ", ".join(f"{l}={t.get('issuer')}" for l, t in items)})
        elif len(certs) > 1:
            findings.append({"level": "info", "url": h, "msg": "같은 CA 의 서로 다른 인증서(CDN 지점 차이일 수 있음)"})
    return findings


def crosscheck_run(names=None):
    cfg = load_xcfg()
    names = names or list(cfg["vantages"])
    runs, skipped, failed = [], [], []
    os.makedirs(RUNS, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    for n in names:
        v = cfg["vantages"].get(n)
        if not v:
            fail(f"vantage 설정에 없는 이름: {n}")
        try:
            res = run_probe(v, n)
        except Exception as e:  # noqa: BLE001 — 한 관점의 실패가 나머지를 막지 않게
            failed.append(f"{n}: {e}")
            continue
        if res is None:
            skipped.append(n)
            continue
        runs.append(res)
        json.dump(res, open(os.path.join(RUNS, f"{stamp}-{n}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    # 수동 관점(핫스팟 등)으로 저장해 둔 가장 최근 결과도 비교에 넣는다(저장 파일 이름: <시각>-<이름>.json)
    findings = compare_probes(runs) if len(runs) >= 2 else []
    st = load_state()
    if len(runs) >= 2:  # 관점이 하나뿐이면 비교가 안 됐으므로 「실행함」으로 치지 않는다(waybar 의 미실행 알림 유지)
        st["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    st["last_vantages"] = [r["label"] for r in runs]
    st["last_findings"] = [f for f in findings if f["level"] in ("mismatch", "warn")]
    st["interval"] = cfg["interval"]
    save_state(st)
    return {"vantages_ok": [r["label"] for r in runs], "skipped_manual": skipped, "failed": failed, "findings": findings,
            "note": "관점이 2개 미만이라 비교하지 못했습니다" if len(runs) < 2 else ""}


def ct_check(update=True):
    """Cert Spotter(CT 로그 모니터)로 카탈로그 호스트의 인증서 발급 이력을 조회하고, **처음 보는 발급 CA** 가 생기면 알린다(첫 실행은 기준선만 저장)."""
    st = load_state()
    ct = st.setdefault("ct", {})
    alerts, report = [], {}
    for dom in ct_domains():
        try:
            d = json.loads(http(f"https://api.certspotter.com/v1/issuances?domain={dom}&include_subdomains=false&expand=issuer"))
        except Exception as e:  # noqa: BLE001
            report[dom] = {"error": str(e)[:80]}
            continue
        issuers = sorted({x["issuer"]["friendly_name"] for x in d})
        newest = max((x["not_before"] for x in d), default="")
        prev = ct.get(dom)
        if prev:
            new_iss = [i for i in issuers if i not in prev["issuers"]]
            if new_iss:
                alerts.append(f"{dom}: 처음 보는 발급 CA {new_iss} (최근 발급 {newest})")
        report[dom] = {"certs": len(d), "issuers": issuers, "newest": newest, "baseline": prev is None}
        ct[dom] = {"issuers": sorted(set(issuers) | set((prev or {}).get("issuers", []))), "newest": newest}
    if update:
        st["last_ct"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        st["ct_alerts"] = alerts
        save_state(st)
    return {"domains": report, "alerts": alerts}


PERIODIC_DAYS = {"ct": 7, "pincheck": 30}


def _age_days(ts):
    if not ts:
        return None
    try:
        return (time.time() - time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))) / 86400
    except ValueError:
        return None


def periodic(force=False):
    """타이머가 매일 부르는 주기 점검. 점검마다 자기 주기가 지났을 때만 돌려 불필요한 외부 접속을 줄인다.
    각 점검의 실패(네트워크 등)는 다른 점검을 막지 않는다. 경고는 상태 파일에 남아 waybar 가 보인다."""
    cfg = load_xcfg()
    done, errors = [], []
    st = load_state()
    due = lambda key, days: force or (_age_days(st.get(key)) is None or _age_days(st.get(key)) >= days)  # noqa: E731
    if due("last_ct", PERIODIC_DAYS["ct"]):
        try:
            ct_check()
            done.append("ct-check")
        except BaseException as e:  # noqa: BLE001 — SystemExit(fail) 도 잡는다
            errors.append(f"ct-check: {e}")
    if due("last_pincheck", PERIODIC_DAYS["pincheck"]):
        try:
            res, ok = pincheck(None)
            st = load_state()
            st["last_pincheck"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            st["pin_alerts"] = [f"{k}: 독립 출처 {sum(1 for r in v['sources'] if r['matched'])}/{v['required_independent_sources']} 만 확인됨"
                                for k, v in res.items() if not v["ok"]]
            save_state(st)
            done.append("pincheck")
        except BaseException as e:  # noqa: BLE001
            errors.append(f"pincheck: {e}")
    try:  # 의존성 감시(S56): 값싼 로컬 스캔이라 주기 판정 없이 매 실행마다. 실패해도 다른 점검을 막지 않는다
        import depwatch  # noqa: PLC0415 — 같은 폴더(스토어 사본 포함), 표준 라이브러리만 쓴다
        n = depwatch.scan()
        done.append(f"depwatch({sum(n.values())}건)")
    except BaseException as e:  # noqa: BLE001
        errors.append(f"depwatch: {e}")
    st = load_state()
    auto = [n for n, v in cfg["vantages"].items() if v.get("kind") in ("local", "ssh")]
    if len(auto) >= 2 and due("last_run", INTERVAL_DAYS[cfg["interval"]]):  # 자동 관점이 2개 미만이면 비교가 안 되므로 돌리지 않는다(waybar 알림이 사람의 설정을 재촉)
        try:
            res = crosscheck_run(auto)
            done.append(f"crosscheck-run({','.join(res['vantages_ok']) or '관점 없음'})")
            errors += res["failed"]
        except BaseException as e:  # noqa: BLE001
            errors.append(f"crosscheck-run: {e}")
    return {"done": done, "errors": errors}


def status_waybar():
    """waybar custom 모듈용 JSON. 주기 안에 있으면 빈 텍스트(모듈이 사라짐), 기한이 지나면 due, 불일치·CT 경고가 있으면 alert."""
    st = load_state()
    try:
        cfg = load_xcfg()
        interval = cfg["interval"]
    except SystemExit:
        interval = "monthly"
    days = INTERVAL_DAYS[interval]
    now = time.time()
    last = None
    if st.get("last_run"):
        try:
            last = time.mktime(time.strptime(st["last_run"][:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            last = None
    problems = [f["msg"] for f in st.get("last_findings", []) if f["level"] == "mismatch"] + list(st.get("ct_alerts", [])) + list(st.get("pin_alerts", []))
    if problems:
        return {"text": "󰒃 신뢰 교차검증 경고", "class": "alert", "tooltip": "\n".join(problems[:6])}
    if last is None:
        return {"text": "󰒃 교차검증 미실행", "class": "due", "tooltip": f"`tools.py crosscheck-run` 로 처음 실행하세요(주기 {interval})"}
    age = (now - last) / 86400
    if age >= days:
        return {"text": f"󰒃 교차검증 {int(age)}일", "class": "due", "tooltip": f"마지막 실행 {int(age)}일 전(주기 {interval}) — `tools.py crosscheck-run`"}
    return {"text": "", "class": "ok", "tooltip": f"교차검증 정상({int(age)}일 전, 주기 {interval})"}


def prune(name, keep, used):
    """CACHE/name/* 중 keep 이 아니고 used(경로 집합)에 없는 버전 폴더를 지운다."""
    base = os.path.join(CACHE, name)
    removed = []
    if not os.path.isdir(base):
        return removed
    used = {os.path.realpath(p) for p in used}
    for v in sorted(os.listdir(base)):
        d = os.path.join(base, v)
        if v.startswith(".") or v == keep or os.path.realpath(d) in used or not os.path.isdir(d):
            continue
        _make_writable_tree(d)
        shutil.rmtree(d)
        removed.append(v)
    return removed


# ---------- 프로젝트 추론·매니페스트 ----------
def infer(repo):
    out = {}
    nv = os.path.join(repo, ".nvmrc")
    if os.path.isfile(nv):
        out["node"] = {"spec": open(nv, encoding="utf-8").read().strip().lstrip("v"), "source": ".nvmrc"}
    pj = os.path.join(repo, "package.json")
    if "node" not in out and os.path.isfile(pj):
        try:
            eng = (json.load(open(pj, encoding="utf-8")).get("engines") or {}).get("node")
        except ValueError:
            eng = None
        m = re.search(r"(\d+)", eng or "")
        if m:
            out["node"] = {"spec": m.group(1), "source": f"package.json engines.node ({eng})"}
    for rt in ("rust-toolchain.toml", "rust-toolchain"):
        rp = os.path.join(repo, rt)
        if os.path.isfile(rp):
            txt = open(rp, encoding="utf-8").read()
            m = re.search(r'channel\s*=\s*"([^"]+)"', txt) or re.match(r"\s*([0-9a-z][^\s#]*)", txt)
            ch = m.group(1) if m else ""
            if re.fullmatch(r"\d+\.\d+(\.\d+)?|stable", ch):
                out["rust"] = {"spec": ch, "source": rt}
            elif ch:
                out["rust_unsupported"] = {"spec": ch, "source": f"{rt} (nightly·beta 등은 도구 층 미지원 — 수동 필요)"}
            break
    pv = os.path.join(repo, ".python-version")
    if os.path.isfile(pv):
        m = re.match(r"\s*(\d+\.\d+(?:\.\d+)?)", open(pv, encoding="utf-8").read())
        if m:
            out["python"] = {"spec": m.group(1), "source": ".python-version"}
    gm = os.path.join(repo, "go.mod")
    if os.path.isfile(gm):
        txt = open(gm, encoding="utf-8").read()
        m = re.search(r"^toolchain\s+go(\d+\.\d+(?:\.\d+)?)", txt, re.M) or re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", txt, re.M)
        if m:
            out["go"] = {"spec": m.group(1), "source": "go.mod"}
    return out


def effective(path):
    with open(path, "rb") as f:
        m = tomllib.load(f)
    tools = {}
    for k, v in (m.get("inferred") or {}).items():
        tools[k] = {"spec": v, "from": "inferred"}
    for k, v in (m.get("override") or {}).items():
        tools[k] = {"spec": v, "from": "override"}
    return tools


def manifest_path(name):
    return os.path.expanduser(f"~/.config/sbox/manifests/{name}.toml")


def q(x):
    return json.dumps(str(x), ensure_ascii=False)


def write_manifest(path, project, repo, inferred, override, resolved, tier=None, network=None):
    lines = ["# sbox 프로젝트 버전 매니페스트(plan dev-sandbox-pilot §29). [inferred]·[resolved] 는 sbox 가 다시 쓰고, [override] 는 사람이 씁니다.",
             "# [resolved] 는 re(실행환경) 도구만 — de(개발환경) 도구는 항상 최신이라 고정하지 않습니다.",
             "[project]", f"name = {q(project)}", f"repo = {q(repo)}"] + ([f"tier = {q(tier)}"] if tier else []) + ["", "[inferred]"]
    for k, v in sorted(inferred.items()):
        lines.append(f"{k} = {q(v['spec'])}  # 출처: {v['source']}".replace("\n", " "))
    lines += ["", "[override]"] + [f"{k} = {q(v)}" for k, v in sorted(override.items())]
    if network:   # [network] 는 사람이 쓰는 구역(송신 허용목록 등 — egress.py 가 읽음). 다시 쓸 때 사라지면 허용 도메인이 조용히 없어진다
        lines += ["", "[network]"]
        for k, v in sorted(network.items()):
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                lines.append(f"{k} = [" + ", ".join(q(x) for x in v) + "]")
            elif isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (str, int)):
                lines.append(f"{k} = {q(v) if isinstance(v, str) else v}")
    for k, v in sorted(resolved.items()):
        lines += ["", f"[resolved.{k}]", f"spec = {q(v['spec'])}", f"version = {q(v['version'])}"] + [f"{kk} = {q(vv)}" for kk, vv in v.items() if kk not in ("spec", "version")]   # 추가 키(docker 의 containerd 등)도 보존
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def plan(a):
    repo = path = None
    update = False
    given = {}
    i = 0
    while i < len(a):
        if a[i] == "--repo":
            repo = os.path.abspath(a[i + 1]); i += 2
        elif a[i] == "--manifest":
            path = os.path.abspath(a[i + 1]); i += 2
        elif a[i] == "--update":
            update = True; i += 1
        elif a[i] == "--tool":
            k, _, v = a[i + 1].partition("="); given[k] = v; i += 2
        else:
            fail(f"plan: 알 수 없는 인자 {a[i]}")
    if not (repo or path):
        fail("plan: --repo 또는 --manifest 가 필요합니다")
    if not path:
        path = manifest_path(os.path.basename(repo.rstrip("/")))
    old = {}
    if os.path.isfile(path):
        with open(path, "rb") as f:
            old = tomllib.load(f)
    project = (old.get("project") or {}).get("name") or (os.path.basename(repo.rstrip("/")) if repo else os.path.basename(path)[:-5])
    repo = repo or (old.get("project") or {}).get("repo", "")
    inferred = infer(repo) if repo and os.path.isdir(repo) else {k: {"spec": v, "source": "기존 매니페스트"} for k, v in (old.get("inferred") or {}).items()}
    override = dict(old.get("override") or {})
    override.update(given)
    docker_ov = override.pop("docker", None)   # 도구가 아니라 「Docker 를 쓰나」 선택 — dockerctl.py 가 읽는다. 도구 해석에서는 빼고 다시 쓸 때 되살린다
    resolved_old = old.get("resolved") or {}
    effective_spec = {k: v["spec"] for k, v in inferred.items()}
    effective_spec.update(override)
    out, resolved, unsupported = {}, {}, []
    cat = catalog()
    for k, spec in list(effective_spec.items()):
        if k not in cat:  # 카탈로그에 없는 도구(예: rust nightly) — 막지 않고 알린다
            unsupported.append(f"{k}={spec} ({inferred.get(k, {}).get('source', '인자')})")
            del effective_spec[k]
    for k in [k for k in inferred if k not in cat]:
        del inferred[k]
    for k, spec in effective_spec.items():
        t = tool(k)
        src = "override" if k in override else inferred.get(k, {}).get("source", "인자")
        if t.get("role") == "de":  # 개발환경 도구: 고정하지 않고 매번 해석(항상 최신)
            ver = resolve(k, spec)
            out[k] = {"spec": spec, "version": ver, "source": src, "how": "최신(de, 고정 안 함)", "role": "de"}
            continue
        prev = resolved_old.get(k) or {}
        if not update and prev.get("spec") == spec and prev.get("version"):
            ver, how = prev["version"], "고정값 재사용"
        else:
            ver = spec.lstrip("v") if re.fullmatch(r"v?\d+\.\d+\.\d+", spec) else resolve(k, spec)
            how = "새로 해석" + (" (--update)" if update else "")
        resolved[k] = {"spec": spec, "version": ver}
        out[k] = {"spec": spec, "version": ver, "source": src, "how": how, "role": "re"}
    if resolved_old.get("docker"):
        resolved["docker"] = resolved_old["docker"]   # 도구 층이 아닌 항목([resolved.docker], dockerctl.py 가 씀)은 다시 쓸 때 그대로 보존
    if docker_ov is not None:
        override["docker"] = docker_ov
    write_manifest(path, project, repo, inferred, override, resolved, tier=(old.get("project") or {}).get("tier"), network=old.get("network"))  # 등급은 사람이 정한 값 — 다시 쓸 때 보존(안 하면 critical 이 조용히 general 로 돌아감)
    return {"manifest": path, "tools": out, "unsupported": unsupported}


def main(a):
    if a and a[0] == "catalog":
        print(json.dumps({k: {"role": v.get("role"), "desc": v.get("desc")} for k, v in catalog().items()}, ensure_ascii=False))
    elif a and a[0] == "resolve" and len(a) in (2, 3):
        print(resolve(a[1], a[2] if len(a) == 3 else None))
    elif len(a) == 3 and a[0] == "fetch":
        print(fetch(a[1], a[2]))
    elif len(a) == 2 and a[0] == "links":
        print(json.dumps(tool(a[1]).get("links") or {}, ensure_ascii=False))
    elif a and a[0] == "prune" and len(a) >= 2:
        keep = a[3] if len(a) >= 4 and a[2] == "--keep" else None
        used = [ln.strip() for ln in sys.stdin if ln.strip()]
        print(" ".join(prune(a[1], keep, used)))
    elif a and a[0] == "probe":
        label = a[a.index("--label") + 1] if "--label" in a else "manual"
        res = json.loads(subprocess.run([sys.executable, PROBE, json.dumps(probe_urls()), label], capture_output=True, text=True, check=True).stdout)
        out = a[a.index("--out") + 1] if "--out" in a else os.path.join(RUNS, f"{time.strftime('%Y%m%dT%H%M%S')}-{label}.json")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print(out)
    elif a and a[0] == "crosscheck":
        runs = [json.load(open(f, encoding="utf-8")) for f in a[1:]]
        fs = compare_probes(runs)
        print(json.dumps({"files": len(runs), "findings": fs}, ensure_ascii=False, indent=1))
        sys.exit(1 if any(f["level"] == "mismatch" for f in fs) else 0)
    elif a and a[0] == "crosscheck-run":
        res = crosscheck_run(a[1:] or None)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1 if any(f["level"] == "mismatch" for f in res["findings"]) else 0)
    elif a and a[0] == "ct-check":
        res = ct_check()
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(1 if res["alerts"] else 0)
    elif a and a[0] == "periodic":
        res = periodic("--force" in a)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(1 if res["errors"] else 0)
    elif a and a[0] == "crosscheck-status":
        print(json.dumps(status_waybar(), ensure_ascii=False))
    elif a and a[0] == "pincheck":
        res, ok = pincheck(a[1] if len(a) > 1 else None)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0 if ok else 1)
    elif len(a) == 2 and a[0] == "infer":
        print(json.dumps(infer(a[1]), ensure_ascii=False))
    elif len(a) == 2 and a[0] == "effective":
        print(json.dumps(effective(a[1]), ensure_ascii=False))
    elif a and a[0] == "plan":
        print(json.dumps(plan(a[1:]), ensure_ascii=False))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
