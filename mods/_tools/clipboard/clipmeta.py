#!/usr/bin/env python3
"""clipmeta — 클립보드 이력(cliphist)의 부가 정보 사이드카 DB

cliphist 는 내용만 저장하므로, 저장 시점의 시각·출처 앱(활성 창)·복사/사용 횟수를 별도 sqlite 에 기록한다.
cliphist 의 DB 형식은 바꾸지 않으므로 기존 이력/도구(clipctl 등)와 그대로 호환된다.
기록이 없는 옛 항목은 부가 정보 없이 보인다.

(Nix 가 @...@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/clipboard-menu.nix)

CLI:  clipmeta.py use <id>        메뉴에서 항목을 복사했을 때 사용 횟수 증가
      clipmeta.py remap           stdin 의 "옛번호 새번호" 쌍으로 번호 이동 (clipctl compact 가 사용)
      clipmeta.py prune           cliphist 에 없는 번호의 기록 정리
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass

CLIPHIST = os.environ.get("CLIPUI_CLIPHIST", "@cliphist@")
HYPRCTL = os.environ.get("CLIPMETA_HYPRCTL", "@hyprctl@")
DB = os.environ.get("CLIPHIST_DB") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "cliphist", "db"
)
META_DB = os.environ.get("CLIPMETA_DB") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "cliphist-meta", "meta.db"
)
SELF_COPY_WINDOW = 5  # 초: 메뉴에서 복사한 직후의 저장 이벤트는 "새로 복사"로 세지 않음

SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
    id         INTEGER PRIMARY KEY,   -- cliphist 번호
    hash       TEXT    NOT NULL,      -- 내용의 sha1
    first_seen INTEGER,               -- 같은 내용을 처음 복사한 시각 (epoch 초)
    created    INTEGER,               -- 이 항목이 (다시) 저장된 시각
    copies     INTEGER NOT NULL DEFAULT 1,  -- 같은 내용을 복사한 횟수
    app        TEXT,                  -- 복사 당시 활성 창의 class
    title      TEXT,                  -- 복사 당시 활성 창의 제목
    uses       INTEGER NOT NULL DEFAULT 0,  -- 메뉴에서 꺼내 쓴 횟수
    last_used  INTEGER
);
CREATE INDEX IF NOT EXISTS item_hash ON item(hash);
CREATE TABLE IF NOT EXISTS selfcopy (hash TEXT PRIMARY KEY, ts INTEGER NOT NULL);
"""


@dataclass
class Meta:
    id: int
    hash: str
    first_seen: int | None
    created: int | None
    copies: int
    app: str | None
    title: str | None
    uses: int
    last_used: int | None


COLUMNS = "id, hash, first_seen, created, copies, app, title, uses, last_used"


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(META_DB), exist_ok=True)
    con = sqlite3.connect(META_DB, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def cliphist(*args: str, data: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([CLIPHIST, "-db-path", DB, *args], input=data, capture_output=True)


def list_ids() -> list[int]:
    """현재 cliphist 의 번호 목록 (최신순)."""
    out = cliphist("list").stdout.decode("utf-8", "replace")
    ids = []
    for line in out.splitlines():
        head = line.split("\t", 1)[0].strip()
        if head.isdigit():
            ids.append(int(head))
    return ids


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def active_window() -> tuple[str, str]:
    """(class, title). 알 수 없으면 ("", "")."""
    env = dict(os.environ)
    if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
        base = os.path.join(env.get("XDG_RUNTIME_DIR", ""), "hypr")
        try:
            dirs = sorted(
                (d for d in os.listdir(base) if os.path.exists(os.path.join(base, d, ".socket.sock"))),
                key=lambda d: os.path.getmtime(os.path.join(base, d)),
            )
            if dirs:
                env["HYPRLAND_INSTANCE_SIGNATURE"] = dirs[-1]
        except OSError:
            pass
    try:
        out = subprocess.run([HYPRCTL, "-j", "activewindow"], capture_output=True, env=env, timeout=2).stdout
        info = json.loads(out or b"{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return ("", "")
    return (str(info.get("class") or ""), str(info.get("title") or ""))


def record(data: bytes, now: int | None = None) -> None:
    """방금 cliphist 에 저장된 내용(data)의 부가 정보를 기록한다."""
    now = now or int(time.time())
    digest = sha1(data)
    ids = list_ids()
    if not ids:
        return
    newest = ids[0]
    # 저장이 건너뛰어졌다면(빈 내용 등) 최신 항목이 이 내용이 아니므로 기록하지 않음
    if sha1(cliphist("decode", str(newest)).stdout) != digest:
        return
    app, title = active_window()

    con = connect()
    with con:
        marker = con.execute("SELECT ts FROM selfcopy WHERE hash = ?", (digest,)).fetchone()
        self_copy = marker is not None and now - marker[0] <= SELF_COPY_WINDOW
        con.execute("DELETE FROM selfcopy WHERE hash = ? OR ts < ?", (digest, now - 3600))

        prev = con.execute(
            f"SELECT {COLUMNS} FROM item WHERE hash = ? AND id != ? ORDER BY created DESC", (digest, newest)
        ).fetchall()
        copies = max((p[4] for p in prev), default=0)
        first_seen = min((p[2] for p in prev if p[2]), default=now)
        uses = max((p[7] for p in prev), default=0)
        last_used = max((p[8] for p in prev if p[8]), default=None)
        if self_copy and prev:
            app, title = prev[0][5], prev[0][6]  # 메뉴에서 다시 복사한 것: 원래 출처 유지, 횟수는 올리지 않음
        else:
            copies += 1
        con.execute(
            f"INSERT OR REPLACE INTO item ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
            (newest, digest, first_seen, now, max(copies, 1), app or None, title or None, uses, last_used),
        )
        # cliphist 에 더 이상 없는 번호(중복 정리·삭제된 항목)는 정리
        alive = ",".join(str(i) for i in ids)
        con.execute(f"DELETE FROM item WHERE id NOT IN ({alive})")
    con.close()


def mark_use(entry_id: int, now: int | None = None) -> None:
    """메뉴에서 항목을 복사하기 직전에 호출: 사용 횟수 증가 + 곧 올 저장 이벤트를 '직접 복사'와 구분."""
    now = now or int(time.time())
    raw = cliphist("decode", str(entry_id)).stdout
    digest = sha1(raw)
    con = connect()
    with con:
        cur = con.execute("UPDATE item SET uses = uses + 1, last_used = ? WHERE id = ?", (now, entry_id))
        if cur.rowcount == 0:
            con.execute(
                f"INSERT INTO item ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_id, digest, None, None, 1, None, None, 1, now),
            )
        con.execute("INSERT OR REPLACE INTO selfcopy (hash, ts) VALUES (?, ?)", (digest, now))
    con.close()


def load_all() -> dict[int, Meta]:
    if not os.path.exists(META_DB):
        return {}
    try:
        con = connect()
        rows = con.execute(f"SELECT {COLUMNS} FROM item").fetchall()
        con.close()
    except sqlite3.Error:
        return {}
    return {r[0]: Meta(*r) for r in rows}


def remap(pairs: list[tuple[int, int]]) -> None:
    """clipctl compact 로 번호가 새로 매겨졌을 때 기록을 새 번호로 옮긴다. 대응이 없는 기록은 삭제."""
    if not os.path.exists(META_DB):
        return
    offset = 10**12
    con = connect()
    with con:
        for old, _new in pairs:
            con.execute("UPDATE item SET id = id + ? WHERE id = ?", (offset, old))
        con.execute("DELETE FROM item WHERE id < ?", (offset,))  # 옮겨지지 않은 옛 기록
        for old, new in pairs:
            con.execute("UPDATE item SET id = ? WHERE id = ?", (new, old + offset))
    con.close()


def prune() -> int:
    ids = list_ids()
    if not os.path.exists(META_DB):
        return 0
    con = connect()
    with con:
        alive = ",".join(str(i) for i in ids) or "-1"
        cur = con.execute(f"DELETE FROM item WHERE id NOT IN ({alive})")
    con.close()
    return cur.rowcount


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "use":
        mark_use(int(argv[2]))
        return 0
    if len(argv) >= 2 and argv[1] == "remap":
        pairs = []
        for line in sys.stdin:
            parts = line.split()
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                pairs.append((int(parts[0]), int(parts[1])))
        remap(pairs)
        return 0
    if len(argv) >= 2 and argv[1] == "prune":
        print(prune())
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
