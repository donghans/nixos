{mkMod, ...}:
# fwupd(펌웨어·Secure Boot 키 데이터베이스 갱신 데몬) — 노트북에서 Secure Boot 를 켠 뒤 `dbx`(금지 목록) 등을 `fwupdmgr` 로 받기 위해 켠다 (plan s5-secure-boot-exec §6, 2026-11-18).
#  - 배경: BIOS 「Reset To Setup Mode」가 `dbx` 까지 지우고 `sbctl enroll-keys` 는 `dbx` 를 복원하지 않는다. 처음에는 Microsoft `DBXUpdate.bin` 을 efivarfs 에 직접 append 했다.
#    이후 갱신은 fwupd(LVFS) 로 받는다: `fwupdmgr refresh && fwupdmgr get-updates && fwupdmgr update`. **설치(`update`)는 자동으로 하지 않는다.**
#  - 데몬(`fwupd.service`)은 D-Bus 활성화 방식이라 평소 상주하지 않는다. 장치를 읽고 쓰는 일꾼이고, 새 정보(메타데이터)를 받는 것은 `fwupdmgr refresh` 다.
#  - upstream 의 `fwupd-refresh.timer`(매시 정각 + 최대 1시간 지연으로 `fwupdmgr refresh`)는 끈다 — 알림용이라 이 호스트에는 과하다.
#    대신 **부팅 3분 뒤 한 번** `fwupd-stale-refresh.service` 가 마지막 확인(`/var/lib/fwupd-check/last-refresh`)이 `staleDays` 일 이상 지났을 때만 `refresh` + `get-updates` 를 하고
#    결과를 `/var/lib/fwupd-check/last-result` 와 journal 에 남긴다(갱신이 있으면 warning). 네트워크가 없으면 stamp 를 갱신하지 않아 다음 부팅에 다시 시도한다.
#  - lanzaboote 가 켜져 있으면 lanzaboote 모듈이 서명된 fwupd EFI 바이너리를 쓰게 해 준다(자동).
#  - 한계: `nixup`(설치·전환)은 dbx 를 건드리지 않는다. 새 노트북에서 BIOS 키를 지웠다면 dbx 가 비어 있다 — 처음 한 번은 `DBXUpdate.bin` 을 직접 적용해야 할 수 있다(plan s5-secure-boot-exec §6, fwupd 가 비어 있는 dbx 에서 갱신을 제안하는지는 확인하지 못했다).
mkMod __curPos "fwupd (LVFS 펌웨어·dbx 갱신 도구, 오래되면 부팅 뒤 한 번 확인)" ({
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
      stamp=${stateDir}/last-refresh
      result=${stateDir}/last-result
      max_age=$(( ${toString cfg.staleDays} * 86400 ))
      mkdir -p ${stateDir}
      if [ -f "$stamp" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$stamp") ))
        if [ "$age" -lt "$max_age" ]; then
          echo "마지막 확인이 $(( age / 86400 ))일 전이라 건너뜀 (기준 ${toString cfg.staleDays}일)"
          exit 0
        fi
      fi
      if ! fwupdmgr refresh --force >"$result.tmp" 2>&1; then
        { echo "fwupdmgr refresh 실패(네트워크?) — 다음 부팅에 다시 시도"; cat "$result.tmp"; } | logger -t fwupd-stale-refresh -p user.warning
        rm -f "$result.tmp"
        exit 0
      fi
      touch "$stamp"
      # get-updates: 갱신이 있으면 종료 코드 0, 없으면 2("Nothing to do")
      if fwupdmgr get-updates >>"$result.tmp" 2>&1; then
        mv "$result.tmp" "$result"
        logger -t fwupd-stale-refresh -p user.warning "fwupd 갱신이 있다 — fwupdmgr get-updates 로 보고 fwupdmgr update 로 적용 (결과: $result)"
      else
        mv "$result.tmp" "$result"
        logger -t fwupd-stale-refresh -p user.info "fwupd 갱신 없음 (결과: $result)"
      fi
    '';
  };
in {
  options = {
    staleDays = lib.mkOption {
      type = lib.types.ints.positive;
      default = 14;
      description = "부팅 뒤 fwupd 메타데이터를 다시 받고 갱신 유무를 확인하는 간격(일). 마지막 확인이 이보다 오래됐을 때만 부팅 3분 뒤 한 번 돈다.";
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
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe checkScript;
        TimeoutStartSec = "5min";
      };
    };
    systemd.timers.fwupd-stale-refresh = {
      wantedBy = ["timers.target"];
      timerConfig.OnBootSec = "3min";
    };
  };
})
