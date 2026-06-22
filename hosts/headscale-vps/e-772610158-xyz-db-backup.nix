{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.headscale-db-backup;

  # GitHub Apps installation token 발급 (RS256 JWT → access token)
  # 출력: token 문자열 (stdout)
  getTokenScript = ''
    APP_ID="${cfg.appId}"
    INSTALLATION_ID="${cfg.installationId}"
    PRIVATE_KEY_FILE="${cfg.privateKeyFile}"

    header=$(printf '{"alg":"RS256","typ":"JWT"}' | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    now=$(date +%s)
    payload=$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$APP_ID" \
      | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    sig=$(printf '%s.%s' "$header" "$payload" \
      | ${pkgs.openssl}/bin/openssl dgst -binary -sha256 -sign "$PRIVATE_KEY_FILE" \
      | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    jwt="$header.$payload.$sig"

    token=$(${pkgs.curl}/bin/curl -sf -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $jwt" \
      "https://api.github.com/app/installations/$INSTALLATION_ID/access_tokens" \
      | ${pkgs.jq}/bin/jq -r '.token')
  '';

  restoreScript = pkgs.writeShellScript "headscale-db-restore" ''
    set -euo pipefail

    DB_PATH="${cfg.dbPath}"

    if [ -f "$DB_PATH" ]; then
      exit 0  # DB 이미 있음 — 복원 불필요
    fi

    echo "headscale DB 없음, GitHub에서 복원 시도..."
    ${getTokenScript}

    # repoUrl에서 owner/repo 추출 (https://github.com/OWNER/REPO.git → OWNER/REPO)
    repo=$(printf '%s' "${cfg.repoUrl}" | sed 's|https://github.com/||;s|\.git$||')

    # db/headscale.sql raw 다운로드 (없으면 첫 배포로 간주하고 조용히 종료)
    sql=$(${pkgs.curl}/bin/curl -sf \
      -H "Authorization: Bearer $token" \
      -H "Accept: application/vnd.github.raw+json" \
      "https://api.github.com/repos/$repo/contents/db/headscale.sql" || true)

    if [ -z "$sql" ]; then
      echo "복원 대상 없음 (첫 배포)"
      exit 0
    fi

    mkdir -p "$(dirname "$DB_PATH")"
    printf '%s' "$sql" | ${pkgs.sqlite}/bin/sqlite3 "$DB_PATH"
    echo "복원 완료: $DB_PATH"
  '';

  backupScript = pkgs.writeShellScript "headscale-db-backup" ''
    set -euo pipefail

    REPO_DIR="${cfg.repoDir}"
    DB_PATH="${cfg.dbPath}"
    ${getTokenScript}

    auth_url="https://x-access-token:$token@${lib.removePrefix "https://" cfg.repoUrl}"

    # clone 없으면 clone, 있으면 pull
    if [ ! -d "$REPO_DIR/.git" ]; then
      ${pkgs.git}/bin/git clone "$auth_url" "$REPO_DIR"
    else
      ${pkgs.git}/bin/git -C "$REPO_DIR" remote set-url origin "$auth_url"
      ${pkgs.git}/bin/git -C "$REPO_DIR" pull --ff-only
    fi

    # DB dump (pre_auth_keys, api_keys INSERT 행 제외)
    mkdir -p "$REPO_DIR/db"
    ${pkgs.sqlite}/bin/sqlite3 "$DB_PATH" .dump \
      | grep -Ev '^INSERT INTO "(pre_auth_keys|api_keys)"' \
      > "$REPO_DIR/db/headscale.sql"

    # 변경 있을 때만 commit + push
    ${pkgs.git}/bin/git -C "$REPO_DIR" \
      -c user.name="headscale-backup" \
      -c user.email="headscale@headscale-backup" \
      add db/headscale.sql
    if ! ${pkgs.git}/bin/git -C "$REPO_DIR" diff --cached --quiet; then
      ${pkgs.git}/bin/git -C "$REPO_DIR" \
        -c user.name="headscale-backup" \
        -c user.email="headscale@headscale-backup" \
        commit -m "chore: headscale db backup"
      ${pkgs.git}/bin/git -C "$REPO_DIR" push origin HEAD
    fi

    # push 후 remote URL에서 token 제거
    ${pkgs.git}/bin/git -C "$REPO_DIR" remote set-url origin "${cfg.repoUrl}"
  '';
in {
  options.services.headscale-db-backup = {
    enable = lib.mkEnableOption "headscale DB backup to GitHub";

    appId = lib.mkOption {
      type = lib.types.str;
      description = "GitHub App ID";
    };

    installationId = lib.mkOption {
      type = lib.types.str;
      description = "GitHub App Installation ID for the backup repo";
    };

    privateKeyFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/nix-secrets/github-apps/private-key.pem";
      description = "Path to GitHub Apps RSA private key (PEM)";
    };

    repoUrl = lib.mkOption {
      type = lib.types.str;
      description = "HTTPS URL of the backup GitHub repo";
    };

    repoDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/headscale-backup";
      description = "Local path for the git clone";
    };

    dbPath = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/headscale/db.sqlite";
      description = "Path to headscale SQLite database";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d ${cfg.repoDir} 0700 headscale headscale -"
      # inject_secrets가 root:root 600으로 생성하므로 매 활성화 시 소유자 교정
      "z ${cfg.privateKeyFile} 0640 headscale headscale -"
    ];

    # headscale 시작 전 DB 없으면 GitHub에서 자동 복원 (litestream ExecStartPre 대체)
    systemd.services.headscale = {
      after = ["network-online.target"];
      wants = ["network-online.target"];
      serviceConfig.ExecStartPre = "${restoreScript}";
    };

    systemd.services.headscale-db-backup = {
      description = "headscale DB backup to GitHub";
      after = ["network-online.target" "headscale.service"];
      wants = ["network-online.target"];
      serviceConfig = {
        Type = "oneshot";
        User = "headscale";
        ExecStart = "${backupScript}";
      };
    };

    systemd.timers.headscale-db-backup = {
      description = "headscale DB backup timer";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnCalendar = "hourly";
        Persistent = true;
      };
    };
  };
}
