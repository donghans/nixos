"""시험용 임시 Postgres: unix 소켓만 열고 실제 schema.sql 을 올린다. 쓰는 곳: test_ctxdata.py · test_ctxui.py.
    pg = pgscratch.start()   # 못 쓰면 None(시험은 건너뛴다) · pg.dsn · pg.home · pg.stop()
"""
import glob, os, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_bin():
    b = os.environ.get("CTX_PG_BIN") or next(iter(sorted(glob.glob("/nix/store/*-postgresql-and-plugins-17*/bin"))), None) or ""
    return b if os.path.exists(os.path.join(b, "initdb")) else None


class Scratch:
    def __init__(self, bindir):
        self.bin = bindir
        self.tmp = tempfile.mkdtemp(prefix="ctxpg-")
        self.data, self.sock = os.path.join(self.tmp, "pg"), os.path.join(self.tmp, "sock")
        os.makedirs(self.sock)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude/projects/-tmp-proj"))
        self.port = str(20000 + (os.getpid() * 7) % 20000)
        self.dsn = f"host={self.sock} port={self.port} dbname=claude_ctx user=claude_ctx"

    def sh(self, *a):
        return subprocess.run(a, capture_output=True, text=True)

    def start(self):
        b = self.bin
        r = self.sh(os.path.join(b, "initdb"), "-D", self.data, "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-locale")
        assert r.returncode == 0, r.stderr
        r = self.sh(os.path.join(b, "pg_ctl"), "-D", self.data, "-w", "-o", f"-c listen_addresses= -c unix_socket_directories={self.sock} -c port={self.port} -c fsync=off",
                    "-l", os.path.join(self.tmp, "pg.log"), "start")
        assert r.returncode == 0, r.stdout + r.stderr
        psql = lambda *a: self.sh(os.path.join(b, "psql"), "-h", self.sock, "-p", self.port, "-U", "postgres", "-v", "ON_ERROR_STOP=1", *a)
        assert psql("-d", "postgres", "-c", "CREATE ROLE claude_ctx LOGIN").returncode == 0
        assert psql("-d", "postgres", "-c", "CREATE DATABASE claude_ctx OWNER claude_ctx").returncode == 0
        r = psql("-d", "claude_ctx", "-f", os.path.join(ROOT, "schema.sql"))
        assert r.returncode == 0, r.stderr
        return self

    def env(self, **extra):
        return dict(os.environ, HOME=self.home, CLAUDE_CTX_HOST="testhost", CLAUDE_CTX_DSN=self.dsn, PYTHONDONTWRITEBYTECODE="1", **extra)

    def stop(self):
        self.sh(os.path.join(self.bin, "pg_ctl"), "-D", self.data, "-m", "immediate", "stop")
        shutil.rmtree(self.tmp, ignore_errors=True)


def start():
    b = find_bin()
    return Scratch(b).start() if b else None
