{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.headscale-db-backup;

  backupScript = pkgs.writeShellScript "headscale-db-backup" ''
    set -euo pipefail

    APP_ID="${cfg.appId}"
    INSTALLATION_ID="${cfg.installationId}"
    PRIVATE_KEY_FILE="${cfg.privateKeyFile}"
    REPO_DIR="${cfg.repoDir}"
    DB_PATH="${cfg.dbPath}"

    # GitHub Apps JWT 생성 (RS256)
    header=$(printf '{"alg":"RS256","typ":"JWT"}' | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    now=$(date +%s)
    payload=$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$APP_ID" \
      | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    sig=$(printf '%s.%s' "$header" "$payload" \
      | ${pkgs.openssl}/bin/openssl dgst -binary -sha256 -sign "$PRIVATE_KEY_FILE" \
      | ${pkgs.coreutils}/bin/base64 -w0 | tr '+/' '-_' | tr -d '=')
    jwt="$header.$payload.$sig"

    # Installation access token 교환
    token=$(${pkgs.curl}/bin/curl -sf -X POST \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $jwt" \
      "https://api.github.com/app/installations/$INSTALLATION_ID/access_tokens" \
      | ${pkgs.jq}/bin/jq -r '.token')

    auth_url="https://x-access-token:''${token}@${lib.removePrefix "https://" cfg.repoUrl}"

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
