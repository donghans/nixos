"""Sandbox — 가짜 hyprctl/systemctl/pkill/posture/journalctl 을 임시 디렉터리에 깔고 시험이 상태를 읽고 쓰게 해 주는 도우미.
동작 정의는 fake_cmd.py 머리말 참고. 시험은 sb.env(...) 로 만든 환경변수로 대상 프로그램을 실행하면 된다."""
import json, os, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAMES = ("hyprctl", "systemctl", "pkill", "posture", "journalctl")


class Sandbox:
    def __init__(self):
        self.dir = tempfile.mkdtemp()                         # FAKE_DIR: 상태/로그 파일이 사는 곳
        self.bin = os.path.join(self.dir, "_bin")
        os.makedirs(self.bin)
        for n in NAMES:                                       # 같은 스크립트를 명령 이름의 심볼릭 링크로(이름으로 동작이 정해짐)
            os.symlink(os.path.join(HERE, "fake_cmd.py"), os.path.join(self.bin, n))

    def path(self, name: str) -> str:
        return os.path.join(self.bin, name)

    def env(self, **extra) -> dict:
        e = dict(os.environ, FAKE_DIR=self.dir, PYTHONDONTWRITEBYTECODE="1")
        e["PATH"] = self.bin + os.pathsep + e.get("PATH", "")
        e.update(extra)
        return e

    # 상태 파일
    def f(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def write(self, name: str, text: str) -> None:
        os.makedirs(os.path.dirname(self.f(name)), exist_ok=True)
        open(self.f(name), "w").write(text)

    def write_json(self, name: str, obj) -> None:
        self.write(name, json.dumps(obj))

    def touch(self, name: str) -> None:
        self.write(name, "")

    def remove(self, name: str) -> None:
        if os.path.exists(self.f(name)):
            os.remove(self.f(name))

    def exists(self, name: str) -> bool:
        return os.path.exists(self.f(name))

    # 기록
    def log(self, name: str) -> list:
        try:
            return open(self.f(name + ".log")).read().splitlines()
        except OSError:
            return []

    def reset_logs(self, *names) -> None:
        for n in names or ("calls", "evals", "signals", "restarts", "starts", "stops", "pkill"):
            self.remove(n + ".log")
