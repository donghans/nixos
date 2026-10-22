# Claude 공유 컨텍스트 저장소(Postgres) — 여러 머신·프로젝트의 Claude Code 대화·사용량을 한곳에 모아 조회한다.
#  - 서버 역할 호스트에서만 켠다(현재 beelink-ser7-co). 클라이언트(훅·수집기·조회)는 mods.devel 의 llm-cli 가 모든 호스트에 설치한다.
#  - 접속: tailnet(MagicDNS `<호스트>:5432`)과 localhost 만. 방화벽은 열지 않는다(tailscale0 는 trustedInterfaces, 그 밖의 인터페이스는 기본 drop).
#    tailnet 에는 다른 사용자 기기도 있어서 신뢰하지 않고 **반드시 scram 비밀번호**를 요구한다(pg_hba).
#  - 비밀번호는 nix 에 두지 않는다(스토어에 평문이 남음). 최초 1회 수동: docs 의 `claude-ctx` 절차 → ~/.config/claude-ctx/dsn (권한 600).
#  - 나중에 클라우드/온프레미스로 옮기면: pg_dump → 새 서버 → 각 머신의 dsn 파일만 교체. 이 모듈은 서버 호스트에서만 끄면 된다.
#  - pgvector 는 설치만 해 둔다(벡터 검색은 필요가 확인될 때). 스키마는 mods/_data/claude-ctx/schema.sql (멱등, 서비스 시작마다 적용).
{mkMod, ...}:
mkMod __curPos "Claude 공유 컨텍스트 저장소 (Postgres)" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: {
  os = lib.mkIf cfg.enable {
    services.postgresql = {
      enable = true;
      package = pkgs.postgresql_17;
      extensions = ps: [ps.pgvector];
      enableTCPIP = true; # listen_addresses = '*' — 외부 도달은 방화벽이 막고 tailscale0 만 열려 있다
      ensureDatabases = ["claude_ctx"];
      ensureUsers = [
        {
          name = "claude_ctx";
          ensureDBOwnership = true;
        }
      ];
      authentication = lib.mkForce ''
        # 소켓: 서버 관리용(postgres 시스템 사용자)만 peer
        local all postgres peer
        # claude_ctx 는 비밀번호로만, localhost 와 tailnet(CGNAT 100.64.0.0/10)에서
        host claude_ctx claude_ctx 127.0.0.1/32 scram-sha-256
        host claude_ctx claude_ctx ::1/128 scram-sha-256
        host claude_ctx claude_ctx 100.64.0.0/10 scram-sha-256
      '';
      settings = {
        password_encryption = "scram-sha-256";
        shared_buffers = "256MB";
      };
    };

    # 스키마 적용(멱등): DB/역할이 만들어진 뒤 postgres 사용자로 실행
    systemd.services.claude-ctx-schema = {
      description = "claude_ctx 스키마 적용";
      # ensureDatabases/ensureUsers 는 postgresql-setup.service 가 만든다 — 그보다 먼저 돌면 "database does not exist" 로 실패한다(실측)
      after = ["postgresql.service" "postgresql-setup.service"];
      requires = ["postgresql.service" "postgresql-setup.service"];
      wantedBy = ["multi-user.target"];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = "postgres";
        ExecStart = "${config.services.postgresql.package}/bin/psql -v ON_ERROR_STOP=1 -d claude_ctx -f ${../../_data/claude-ctx/schema.sql}";
      };
    };
  };
})
