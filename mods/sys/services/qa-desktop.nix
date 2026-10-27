# QA 데스크톱(incus VM `qa-desktop`) — 화면을 사람과 같이 보며 headed 브라우저로 QA 하는 공용 환경을 **선언**하고, 없으면 **만든다**.
#  - 켜면(호스트 toml 의 `qa-desktop = true`):
#      1. `qa-desktop-ctl`(ensure·provision·status·snapshot·destroy)을 설치한다.
#      2. 로그인 때 사용자 서비스 `qa-desktop-ensure` 가 `ensure` 를 백그라운드로 돌린다: VM 이 **없으면** Ubuntu 26.04 desktop 이미지로 만들고 프로비저닝한다
#         (사용자 `qa`·ssh 키·GDM 자동 로그인·화면 잠금 끔·Auto Move Windows 규칙·Playwright·도구). 약 5분, 처음에는 이미지 1.4GB 를 받는다.
#         **이미 있는 VM 은 건드리지 않는다**(직접 만든 기존 VM 은 「채택」만 한다). 선언을 바꾼 뒤 기존 VM 에 반영하려면 `qa-desktop-ctl provision`.
#      3. Claude 전역 지침에 VM 사용 규칙을 넣고 스킬 donghans-qa-desktop 을 등록한다(mods/devel/apps/llm-cli.nix).
#  - incus-win11 과의 차이: win11 은 프로필·설치 ISO 만 선언하고 인스턴스는 사람이 만든다. 이 mod 는 서버의 incus-*-lxc.nix 처럼 「없으면 만든다」까지 하되,
#    OS 재빌드 없이 `nixup home` 만으로 배포되도록 사용자 서비스로 둔다(사용자는 incus-admin 그룹).
#  - 선언은 아래 `decl` 한 곳. 새 프로젝트의 창 배치 규칙은 `projects` 에 「이름 = 가상 데스크톱 번호」를 추가하고 `nixup home` 뒤 `qa-desktop-ctl provision`.
#  - 설명·검증 기록·되돌리는 방법: mods/_tools/qa-desktop/README.md  ·  도구: mods/_tools/qa-desktop/ · mods/_data/claude-skills/donghans-qa-desktop/scripts/
{mkMod, ...}:
mkMod __curPos "QA 데스크톱 VM(incus) 선언·생성·사용 지침" ({
  config,
  lib,
  pkgs,
  ...
}: let
  decl = {
    name = "qa-desktop";
    cpu = "4";
    memory = "8GiB";
    disk = "60GiB";
    image = "images:ubuntu/26.04/desktop"; # incus 의 images: 원격(simplestreams). 데스크톱 변형이라 GNOME 50 Wayland·gdm3·pipewire 가 들어 있다
    user = "qa"; # VM 의 데스크톱 사용자(이미지의 ubuntu, uid 1000 을 이름 변경 — /run/user/1000 을 가정한 도구가 그대로 동작)
    playwright = "~1.63.0"; # 모든 프로젝트가 공유하는 버전. `^` 면 새 마이너가 나올 때마다 달라진다
    # 프로젝트별 창 배치 규칙: Chromium `--class=<이름>-qa` 로 띄운 창이 가상 데스크톱 <번호> 로 자동 이동(GNOME Auto Move Windows). 규칙이 없는 프로젝트는 지금 보는 데스크톱에 뜬다.
    projects = {
      genple = 2;
      tot = 3;
    };
    ssh_key = "~/.ssh/qa_desktop_ed25519"; # 호스트 쪽 개인키(없으면 ensure 가 만든다). 공개키가 VM 의 qa 계정에 들어간다
  };
  configJson = pkgs.writeText "qa-desktop.json" (builtins.toJSON (decl
    // {
      provision = "${../../_tools/qa-desktop/provision.sh}";
      tools_dir = "${../../_data/claude-skills/donghans-qa-desktop/scripts}";
    }));
  ctl = pkgs.writeShellScriptBin "qa-desktop-ctl" ''
    export QA_DESKTOP_CONFIG=${configJson}
    # incus 는 데몬과 버전이 맞는 시스템 것을 쓴다(virtualisation.incus 가 설치)
    export PATH=/run/current-system/sw/bin:${lib.makeBinPath [pkgs.openssh pkgs.coreutils pkgs.gnugrep]}:$PATH
    exec ${pkgs.python3}/bin/python3 ${../../_tools/qa-desktop/qa_desktop_ctl.py} "$@"
  '';
in {
  os.assertions = [
    {
      assertion = config.mods.sys.services.incus.enable;
      message = "mods.sys.services.qa-desktop 는 mods.sys.services.incus.enable = true 가 필요합니다";
    }
  ];

  hm = {
    home.packages = [ctl];

    # 로그인 때 한 번: 없으면 만들고 프로비저닝(백그라운드 — Type=simple 이라 nixup/로그인을 막지 않는다). 있으면 아무것도 바꾸지 않는다.
    # incus 가 아직 부팅 중이면 ensure 가 종료 코드 3 으로 끝나 재시도한다(시간당 5번까지).
    systemd.user.services.qa-desktop-ensure = {
      Unit = {
        Description = "Ensure the qa-desktop incus VM exists (create + provision when absent; never modifies an existing VM)";
        StartLimitIntervalSec = 3600;
        StartLimitBurst = 5;
      };
      Service = {
        Type = "simple";
        ExecStart = "${ctl}/bin/qa-desktop-ctl ensure";
        Restart = "on-failure";
        RestartSec = 120;
        Nice = 10;
      };
      Install.WantedBy = ["default.target"];
    };
  };
})
