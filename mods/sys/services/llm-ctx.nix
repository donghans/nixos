# Claude 공유 컨텍스트 저장소(Postgres) — 여러 머신·프로젝트의 Claude Code 대화·사용량을 한곳에 모아 조회한다.
#  - 서버 역할 호스트에서만 켠다(현재 beelink-ser7-co). 클라이언트(훅·수집기·조회)는 mods.devel 의 llm-cli 가 모든 호스트에 설치한다.
#  - 접속: localhost 와 허용 목록의 tailnet 기기(MagicDNS `<호스트>:5432`)만. 방화벽은 열지 않는다(tailscale0 는 trustedInterfaces, 그 밖의 인터페이스는 기본 drop).
#    tailnet 에는 다른 사용자 기기도 있어서 허용 목록(IP)에 있는 기기만 받는다. **비밀번호·dsn 파일 없음** — 전부 이 파일(nix)로만 관리된다.
#  - 나중에 클라우드/온프레미스로 옮기면: pg_dump → 새 서버 → 각 머신의 dsn 파일만 교체. 이 모듈은 서버 호스트에서만 끄면 된다.
#  - pgvector 는 설치만 해 둔다(벡터 검색은 필요가 확인될 때). 스키마는 mods/_tools/llm-ctx/schema.sql (멱등, 서비스 시작마다 적용).
{mkMod, ...}:
mkMod __curPos "Claude 공유 컨텍스트 저장소 (Postgres)" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: let
  # 접속을 허용할 tailnet 기기(허용 목록 — 비밀번호와 별개의 2중 장치). 새 기기를 쓰려면 여기에 tailnet IP 를 추가한다.
  # headscale 이 IP 를 재할당하면(재등록 시) 그 기기는 접속이 막힌다 — 조용히 실패하지 않고 인증 거부로 보인다(fail-closed).
  #   100.64.0.4 msi-summit-me (확인: 2026-10-22 tailscale status)
  allowedClients = ["100.64.0.4"]; # 서버 자신(100.64.0.1)은 소켓을 쓰므로 TCP 허용이 없다 — 컨테이너·VM 의 NAT 출구가 이 주소로 보여도 못 들어온다
in {
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
      identMap = "ctx ${config.workspace.username} claude_ctx";
      authentication = lib.mkForce ''
        # 서버 관리용(postgres 시스템 사용자)은 소켓 peer
        local all postgres peer
        # 이 서버 머신의 사용자 계정은 소켓 peer 로 비밀번호 없이(ident map 'ctx') — 같은 머신의 다른 사용자·컨테이너는 소켓에 못 들어온다
        local claude_ctx claude_ctx peer map=ctx
        # 원격 머신은 **허용 목록의 tailnet 출발지 IP 로만**, 비밀번호 없이(trust). 신뢰 근거: (1) 출발지 IP 는 WireGuard 로 인증된 tailnet 주소이고
        # (2) 방화벽(tailscale 모듈)이 tailscale0 밖에서 온 100.64.0.0/10 출발지를 버리며 (3) 이 포트는 tailscale0 밖으로 열려 있지 않다.
        # 남는 위험: 허용된 그 기기 안의 다른 프로그램이 접속할 수 있다(단일 사용자 노트북 전제). 비밀번호·dsn 파일이 없어 유실될 비밀이 없다.
        ${lib.concatMapStringsSep "\n" (ip: "host claude_ctx claude_ctx ${ip}/32 trust") allowedClients}
      '';
      settings = {
        password_encryption = "scram-sha-256";
        shared_buffers = "256MB";
      };
    };

    # 매일 03:30 덤프(최신 1개만 유지 — 덤프 파일이 같은 디스크에 있으므로 디스크 고장은 못 막는다. 원본은 각 머신의 트랜스크립트이기도 함).
    # 필요성: Claude Code 는 오래된 로컬 트랜스크립트를 정리하므로, 시간이 지나면 이 DB 가 옛 대화의 유일한 사본이 된다.
    services.postgresqlBackup = {
      enable = true;
      databases = ["claude_ctx"];
      startAt = "*-*-* 03:30:00";
      compression = "zstd";
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
        ExecStart = "${config.services.postgresql.package}/bin/psql -v ON_ERROR_STOP=1 -d claude_ctx -f ${../../_tools/llm-ctx/schema.sql}";
      };
    };
  };
})
