#!/usr/bin/env python3
"""nixstrap.lib-repo.py — nixstrap.sh용 레포지토리/설정 서브커맨드 헬퍼

서브커맨드:
  check-repo   <repo_tmp>             → base.toml에서 git.nixosRepo 출력
  update-repo  <repo_tmp> <new_repo>  → base.toml의 git.nixosRepo를 in-place 수정
  sync-remote  <repo_path>            → git remote origin에서 owner/repo 자동 감지 후 base.toml 동기화
  username     <repo_tmp>             → base.toml에서 username 출력
  list-hosts   <repo_tmp>             → hostname|type|preset 형식으로 호스트 목록 출력
  list-presets <repo_tmp>             → 프리셋 이름 출력 (iso 제외)
  disk-labels  <repo_tmp> <host>      → BOOT_LABEL DISK_LABEL 출력 (공백 구분)
"""

import sys
import os
import re
import tomllib


def cmd_check_repo(args):
    repo_tmp = args[0]
    base_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        print(base.get("git", {}).get("nixosRepo", ""))
    except Exception:
        print("")


def _update_field(toml_path, pattern, new_value):
    """_base.toml에서 정규식 패턴에 일치하는 값을 in-place 수정."""
    with open(toml_path, "r") as f:
        content = f.read()
    content = re.sub(pattern, f'\\g<1>{new_value}\\g<2>', content)
    with open(toml_path, "w") as f:
        f.write(content)


def _apply_if_changed(toml_path, label, pattern, old_val, new_val):
    """new_val이 old_val과 다를 때만 _update_field 실행 후 [sync] 메시지 출력."""
    if new_val and new_val != old_val:
        _update_field(toml_path, pattern, new_val)
        print(f"[sync] {label}: '{old_val}' → '{new_val}'")


def _fetch_github_user(owner):
    """GitHub API로 사용자 정보 조회. 실패 시 None 반환.
    email이 비공개인 경우 {id}+{login}@users.noreply.github.com으로 구성."""
    import urllib.request
    import urllib.error
    import json
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{owner}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "nixstrap"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        name  = data.get("name") or ""
        email = data.get("email") or ""
        uid   = data.get("id")
        login = data.get("login", owner)
        if not email and uid:
            email = f"{uid}+{login}@users.noreply.github.com"
        return {"name": name, "email": email}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        return None


def _readline_input(prompt, prefill=""):
    """readline pre-fill을 지원하는 단일행 입력. 실패 시 일반 input()으로 폴백."""
    try:
        import readline
        readline.set_startup_hook(lambda: readline.insert_text(prefill))
        try:
            return input(prompt).strip()
        finally:
            readline.set_startup_hook()
    except ImportError:
        val = input(f"{prompt}[{prefill}] ").strip()
        return val or prefill


def _sync_review(fields):
    """변경 예정 필드를 테이블로 보여주고 유저 확인/편집 후 최종값 반환.

    fields: list of dict(label, pattern, cur, proposed)
      proposed=None  → 자동 감지 불가, 반드시 직접 입력
    반환: list of dict(..., value=최종값)  또는  None(건너뛰기)
    """
    CYAN = "\033[36m"; YELLOW = "\033[33m"; DIM = "\033[2m"; NC = "\033[0m"

    print()
    print(f"  {CYAN}[sync]{NC} _base.toml 변경 감지됨:\n")
    print(f"  {'필드':<14} {'현재값':<32} 감지된 값")
    print(f"  {DIM}{'─' * 66}{NC}")
    for f in fields:
        proposed_str = f["proposed"] if f["proposed"] is not None else f"{YELLOW}(직접 입력){NC}"
        print(f"  {f['label']:<14} {f['cur']:<32} → {proposed_str}")
    print()

    while True:
        try:
            choice = input(
                f"  {CYAN}[Enter/a]{NC} 전체 적용   {CYAN}[e]{NC} 필드별 편집   {CYAN}[s]{NC} 건너뛰기 : "
            ).strip().lower()
        except EOFError:
            return None

        if choice in ("a", ""):
            result = []
            for f in fields:
                if f["proposed"] is not None:
                    result.append({**f, "value": f["proposed"]})
                else:
                    # proposed 없는 필드(username)는 반드시 입력
                    try:
                        val = _readline_input(f"  {f['label']}: ", f["cur"])
                    except EOFError:
                        return None
                    result.append({**f, "value": val})
            return result

        if choice == "e":
            result = []
            for f in fields:
                prefill = f["proposed"] if f["proposed"] is not None else f["cur"]
                try:
                    val = _readline_input(f"  {f['label']}: ", prefill)
                except EOFError:
                    return None
                result.append({**f, "value": val})
            return result

        if choice == "s":
            return None


def cmd_sync_remote(args):
    """git remote origin URL에서 owner/repo를 추출하여 base.toml을 자동 동기화."""
    import subprocess
    repo_path = args[0]

    try:
        remote_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    m = re.search(r"[:/]([^/:][^/]*/[^/]+?)(?:\.git)?$", remote_url)
    if not m:
        return

    detected = m.group(1)

    base_path = os.path.join(repo_path, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
    except Exception:
        return

    current_repo = base.get("git", {}).get("nixosRepo", "")
    if current_repo == detected:
        return

    git_sec = base.get("git", {})
    cur_name     = git_sec.get("name", "")
    cur_email    = git_sec.get("email", "")
    cur_username = base.get("username", "")

    owner = detected.split("/")[0]
    gh = _fetch_github_user(owner)
    if not gh:
        print(f"[sync] GitHub API 사용 불가 — name/email 직접 입력이 필요합니다.")

    fields = [
        {"label": "nixosRepo", "pattern": r'(nixosRepo\s*=\s*")[^"]*(")', "cur": current_repo, "proposed": detected},
        {"label": "git.name",  "pattern": r'(name\s*=\s*")[^"]*(")',       "cur": cur_name,     "proposed": gh["name"]  if gh else None},
        {"label": "git.email", "pattern": r'(email\s*=\s*")[^"]*(")',      "cur": cur_email,    "proposed": gh["email"] if gh else None},
        {"label": "username",  "pattern": r'(username\s*=\s*")[^"]*(")',   "cur": cur_username, "proposed": None},
    ]

    final = _sync_review(fields)
    if final is None:
        return

    for f in final:
        _apply_if_changed(base_path, f["label"], f["pattern"], f["cur"], f["value"])


def cmd_update_repo(args):
    repo_tmp, new_repo = args[0], args[1]
    toml_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    _update_field(toml_path, r'(nixosRepo\s*=\s*")[^"]*(")', new_repo)


def cmd_username(args):
    repo_tmp = args[0]
    host = args[1] if len(args) > 1 else None
    base_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        base_user = base.get("username", "")
    except Exception:
        base_user = ""
    if host:
        host_path = os.path.join(repo_tmp, "hosts", f"{host}.toml")
        try:
            with open(host_path, "rb") as f:
                h = tomllib.load(f)
            print(h.get("username", base_user))
            return
        except Exception:
            pass
    print(base_user)


def cmd_list_hosts(args):
    repo_tmp = args[0]
    hosts_dir = os.path.join(repo_tmp, "hosts")
    entries = []
    for entry in sorted(os.listdir(hosts_dir)):
        # hosts/<hostname>.toml 형식 (평탄 구조)
        if not entry.endswith(".toml") or entry == "_base.toml" or entry.startswith("_preset."):
            continue
        hostname = entry[:-5]  # .toml 제거
        toml_path = os.path.join(hosts_dir, entry)
        with open(toml_path, "rb") as f:
            h = tomllib.load(f)
        # 4번째 필드: 이전에 remote 전용 구분용이었으나 nixstrap에서도 [deploy] 호스트 설치 가능
        deploy_flag = ""
        entries.append(f"{hostname}|{h.get('type', '?')}|{h.get('preset', '?')}|{deploy_flag}")
    print("\n".join(entries))


def cmd_list_presets(args):
    repo_tmp = args[0]
    hosts_dir = os.path.join(repo_tmp, "hosts")
    names = sorted(
        f[len("_preset."):-len(".toml")]
        for f in os.listdir(hosts_dir)
        if f.startswith("_preset.") and f.endswith(".toml") and f != "_preset.iso.toml"
    )
    print("\n".join(names))


def cmd_disk_labels(args):
    repo_tmp, host = args[0], args[1]
    with open(os.path.join(repo_tmp, "hosts", "_base.toml"), "rb") as f:
        base = tomllib.load(f)
    host_path = os.path.join(repo_tmp, "hosts", f"{host}.toml")
    host_data = {}
    if os.path.exists(host_path):
        with open(host_path, "rb") as f:
            host_data = tomllib.load(f)

    boot_dev = host_data.get("bootDevice", base["bootDevice"])
    disk_dev = host_data.get("diskDevice", base["diskDevice"])

    def extract_label(path):
        prefix = "/dev/disk/by-label/"
        return path[len(prefix):] if path.startswith(prefix) else ""

    print(extract_label(boot_dev), extract_label(disk_dev))


SUBCOMMANDS = {
    "check-repo":   cmd_check_repo,
    "update-repo":  cmd_update_repo,
    "sync-remote":  cmd_sync_remote,
    "username":     cmd_username,
    "list-hosts":   cmd_list_hosts,
    "list-presets": cmd_list_presets,
    "disk-labels":  cmd_disk_labels,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: nixstrap.lib-repo.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        sys.exit(1)
    SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
