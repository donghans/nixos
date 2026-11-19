{mkMod, ...}:
# fwupd(펌웨어·Secure Boot 키 데이터베이스 갱신 데몬) — 노트북에서 Secure Boot 를 켠 뒤 `dbx`(금지 목록) 등을 `fwupdmgr` 로 받기 위해 켠다 (plan s5-secure-boot-exec §6, 2026-11-18).
#  - 배경: BIOS 「Reset To Setup Mode」가 `dbx` 까지 지우고 `sbctl enroll-keys` 는 `dbx` 를 복원하지 않는다. 처음에는 Microsoft `DBXUpdate.bin` 을 efivarfs 에 직접 append 했다.
#    이후 갱신은 fwupd(LVFS) 로 받는다: `fwupdmgr refresh && fwupdmgr get-updates && fwupdmgr update`. **설치(`update`)는 자동으로 하지 않는다.**
#  - 데몬(`fwupd.service`)은 D-Bus 활성화 방식이라 평소 상주하지 않는다. 장치를 읽고 쓰는 일꾼이고, 새 정보(메타데이터)를 받는 것은 `fwupdmgr refresh` 다.
#  - upstream 의 `fwupd-refresh.timer`(매시 정각 + 최대 1시간 지연으로 `fwupdmgr refresh`)는 끈다 — 알림용이라 이 호스트에는 과하다.
#    대신 `fwupd-stale-refresh.service` 가 아래 「검사 시점」에 한 번 돌아 갱신 유무를 `/var/lib/fwupd-check/last-result` 와 journal 에 남긴다(갱신이 있으면 warning).
#  - lanzaboote 가 켜져 있으면 lanzaboote 모듈이 서명된 fwupd EFI 바이너리를 쓰게 해 준다(자동).
#  - **dbx 는 자동으로 쓰지 않는다(2026-11-19 결정)**: dbx 가 바뀌면 PCR 7 이 달라져 TPM+PIN 등록이 깨진다. 내가 모르게 TPM 이 깨지는 경로를 없애려고, dbx 를 채우거나(`nixseal sb dbx`)
#    갱신하는 것(`fwupdmgr update`, 실제로는 `nixseal sb dbx-update`)은 **사용자가 직접** 한다. 대신 알림을 보낸다: 로그인할 때(`sb-notify`) dbx 변수가 없으면 긴급 알림, fwupd 결과에 갱신이 있으면 일반 알림 —
#    본문에 칠 명령과 「TPM 등록이 깨질 수 있다」는 고지가 들어 있어 알림 센터(`notif`)에서 복사해 쓴다. fwupd 는 dbx 가 없으면 갱신을 거부하므로(소스·VM 시험 확인) 비어 있으면 먼저 채워야 한다.
#  - 검사 시점(시간 기반 타이머 없음): NetworkManager 가 연결(`up`)되거나 인터넷이 확인(`connectivity-change`=FULL)될 때 훅이 서비스를 시작한다(NetworkManager 를 안 쓰는 호스트는 `network-online.target` 에 건다).
#    이번 부팅에서 확인을 마쳤다는 표시(`/run/fwupd-check-done`, 재부팅하면 사라짐)가 있으면 바로 끝낸다. 메타데이터 새로 받기(`refresh`, 네트워크 필요)가 필요한데 못 받았으면 표시를 남기지 않아
#    다음 연결 이벤트에 다시 시도한다. refresh 는 마지막 성공이 `staleDays` 일보다 오래됐을 때만 하고, 갱신 유무(`get-updates`, 로컬 메타데이터)는 매번 확인해 결과를 적어 둔다.
mkMod __curPos "fwupd (LVFS 펌웨어·dbx 갱신 도구, 네트워크가 연결되면 갱신 유무를 확인하고 알림)" ({
  cfg,
  config,
  lib,
  pkgs,
  ...
}: let
  fw = config.services.fwupd.package;
  stateDir = "/var/lib/fwupd-check";
  checkScript = pkgs.writeShellApplication {
    name = "fwupd-stale-refresh";
    runtimeInputs = [fw pkgs.coreutils pkgs.util-linux];
    text = ''
      done_mark=/run/fwupd-check-done
      if [ -e "$done_mark" ]; then
        echo "이번 부팅에서는 이미 확인함 — 다시 하려면 rm $done_mark"
        exit 0
      fi
      stamp=${stateDir}/last-refresh
      result=${stateDir}/last-result
      max_age=$(( ${toString cfg.staleDays} * 86400 ))
      mkdir -p ${stateDir}
      tmp="$result.tmp"
      : > "$tmp"
      # 1. 메타데이터는 오래됐을 때만 새로 받는다(네트워크 필요). 못 받으면 기록만 하고 캐시된 메타데이터로 계속한다(다음 주기·다음 연결 때 다시 시도).
      need_refresh=1
      refresh_failed=0
      if [ -f "$stamp" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$stamp") ))
        if [ "$age" -lt "$max_age" ]; then need_refresh=0; fi
      fi
      if [ "$need_refresh" = 1 ]; then
        if fwupdmgr refresh --force >>"$tmp" 2>&1; then
          touch "$stamp"
        else
          refresh_failed=1
          echo "fwupdmgr refresh 실패(네트워크?) — 다음 연결 때 다시 시도" | logger -t fwupd-stale-refresh -p user.info
        fi
      fi
      # 2. 갱신 유무는 매번 적어 둔다(로컬 메타데이터만 읽음). get-updates: 갱신이 있으면 종료 코드 0, 없으면 2("Nothing to do")
      if fwupdmgr get-updates >>"$tmp" 2>&1; then
        mv "$tmp" "$result"
        logger -t fwupd-stale-refresh -p user.warning "fwupd 갱신이 있다 — fwupdmgr get-updates 로 보고 fwupdmgr update 로 적용 (결과: $result)"
      else
        mv "$tmp" "$result"
        logger -t fwupd-stale-refresh -p user.info "fwupd 갱신 없음 (결과: $result)"
      fi
      # 이번 부팅에서 할 확인을 마쳤다는 표시(refresh 가 필요했는데 못 받았으면 남기지 않는다 → 다음 연결 이벤트에 재시도)
      if [ "$refresh_failed" = 0 ]; then
        touch "$done_mark"
      fi
    '';
  };
  # 로그인 때·fwupd 결과가 바뀔 때 돈다(사용자 권한). efivars 와 결과 파일은 누구나 읽을 수 있다. 같은 알림을 한 번만 보내려고 런타임 폴더에 표시를 남긴다.
  notifyScript = pkgs.writeShellApplication {
    name = "sb-notify";
    runtimeInputs = [pkgs.libnotify pkgs.coreutils pkgs.gnugrep pkgs.gawk];
    text = ''
      efivars=/sys/firmware/efi/efivars
      guid_db=d719b2cb-3d3a-4596-a3bc-dad00e67656f
      result=${stateDir}/last-result
      seen=''${XDG_RUNTIME_DIR:-/tmp}/sb-notify
      mkdir -p "$seen"
      once() { # 이름 -> 이미 보냈으면 1
        if [ -e "$seen/$1" ]; then return 1; fi
        touch "$seen/$1"
      }
      if [ -d "$efivars" ] && [ ! -e "$efivars/dbx-$guid_db" ]; then
        if once dbx-missing; then
          notify-send -a secure-boot -u critical "Secure Boot: dbx 가 비어 있습니다" \
            "채우기(복사해서 실행): sudo nixseal sb dbx
      ※ Secure Boot 상태가 바뀌어 TPM+PIN 등록이 깨질 수 있습니다. 채운 뒤 재부팅해서 TPM 을 다시 등록하세요(TPM 을 아직 안 쓰면 상관없음)."
        fi
      elif [ -r "$result" ] && grep -q 'New version' "$result"; then
        ver=$(grep -m1 'New version' "$result" | awk '{print $NF}')
        if once "dbx-update-$ver"; then
          notify-send -a secure-boot -u normal "Secure Boot: dbx 갱신이 있습니다 ($ver)" \
            "적용(복사해서 실행): sudo nixseal sb dbx-update
      (집이고 낯선 사람이 없는지 먼저 묻습니다)
      ※ 적용하면 PCR 7 이 바뀌어 TPM+PIN 등록이 깨질 수 있습니다. 바로 재부팅해서 복구 암호를 한 번 입력하고 TPM 을 다시 등록하세요."
        fi
      fi
    '';
  };
in {
  options = {
    staleDays = lib.mkOption {
      type = lib.types.ints.positive;
      default = 14;
      description = "fwupd 메타데이터를 새로 받는(refresh) 최소 간격(일). 마지막 성공이 이보다 오래됐을 때만 받는다(갱신 유무 확인은 매 부팅 첫 연결 때 한다).";
    };
  };
  os = lib.mkIf cfg.enable {
    services.fwupd.enable = true;
    # upstream 의 매시간 refresh 타이머는 끈다(nixpkgs 모듈이 timers.target 에 걸어 둔 것을 비운다).
    systemd.timers.fwupd-refresh.wantedBy = lib.mkForce [];
    systemd.services.fwupd-stale-refresh = {
      # 주의: Description 은 부팅 중 콘솔(VT)에 `Starting …` 으로 찍힌다. VT 에는 한글 글꼴이 없어 네모로 보이므로 영어로 쓴다.
      description = "Refresh fwupd metadata when stale and record available updates (no install)";
      wants = ["network-online.target"];
      after = ["network-online.target"];
      # NetworkManager 를 안 쓰는 호스트는 네트워크가 온라인이 될 때 시작(NM 호스트는 위 훅이 시작).
      wantedBy = lib.mkIf (!config.networking.networkmanager.enable) ["network-online.target"];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe checkScript;
        TimeoutStartSec = "5min";
      };
    };
    # NetworkManager 호스트: 연결·인터넷 확인 이벤트가 곧바로 서비스를 시작한다(wifi 가 늦게 붙어도 즉시). 서비스 안의 표시 파일이 부팅당 한 번으로 줄인다.
    networking.networkmanager.dispatcherScripts = lib.mkIf config.networking.networkmanager.enable [
      {
        type = "basic";
        source = pkgs.writeShellScript "fwupd-check-on-up" ''
          case "$2" in
            up) systemctl start --no-block fwupd-stale-refresh.service ;;
            connectivity-change)
              if [ "''${CONNECTIVITY_STATE:-}" = FULL ]; then
                systemctl start --no-block fwupd-stale-refresh.service
              fi
              ;;
          esac
        '';
      }
    ];
  };
  hm = lib.mkIf cfg.enable {
    systemd.user.services.sb-notify = {
      Unit.Description = "Notify about Secure Boot dbx state (missing or update available)";
      Service = {
        Type = "oneshot";
        ExecStart = lib.getExe notifyScript;
      };
      Install.WantedBy = ["graphical-session.target"];
    };
    systemd.user.paths.sb-notify = {
      Unit.Description = "Re-check dbx notification when the fwupd result changes";
      Path.PathChanged = "${stateDir}/last-result";
      Install.WantedBy = ["default.target"];
    };
  };
})
