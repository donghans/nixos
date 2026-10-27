"""시험 공용 하네스. 시험 파일마다 따로 정의하던 check()/카운터/가짜 실행 파일 만들기를 한 곳으로 모은 것."""
import os, stat, sys, tempfile


def checker(verbose: bool = False):
    """(check, finish) 를 돌려준다.
      check(이름, 조건, 부가설명="")  — 실패하면 `  FAIL 이름 부가설명` 출력(verbose 면 통과도 출력)
      finish(제목)                  — `제목 N 통과 / M 실패` 를 출력하고 종료 코드로 끝냄"""
    n = {"ok": 0, "bad": 0}

    def check(name, cond, extra=""):
        if cond:
            n["ok"] += 1
            if verbose:
                print("  ok  ", name)
        else:
            n["bad"] += 1
            print("  FAIL", name, extra)

    def finish(title):
        print(f"\n{title} {n['ok']} 통과 / {n['bad']} 실패")
        sys.exit(1 if n["bad"] else 0)

    check.counts = n
    return check, finish


def script(dirpath: str, name: str, body: str) -> str:
    """dirpath/name 에 실행 가능한 python 스크립트를 만든다(가짜 실행 파일 한두 개짜리 임시용)."""
    p = os.path.join(dirpath, name)
    with open(p, "w") as f:
        f.write("#!/usr/bin/env python3\n" + body)
    os.chmod(p, 0o755)
    return p


def tmpdir() -> str:
    return tempfile.mkdtemp()
