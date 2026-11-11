# embedctl / embedctlui — MSI Summit E16Flip A12UDT(보드 MS-1592) 전용: EC 상태(충전 상한·성능 모드·Cooler Boost)를 허용 목록으로 읽고 다루는 CLI 와 TUI.
# 본체는 mods/_tools/desktop/embedctl/ (README.md), 설계·검증은 ctx `plan/embedctl-lockdown`(sysfs 전환)·`plan/embedctl-구현`(원래 WMI 설계).
# 기종 전용이라 모든 노트북에 깔지 않고 호스트 toml 의 `[mods.gui.apps] embedctl = true` 로만 켠다.
#
# **lockdown 아래에서 동작하도록 debugfs/WMI 를 쓰지 않고 sysfs(커널 모듈 msi-ec)만 쓴다.** msi-ec 는 `kernel-lockdown` mod 의 `boot.extraModulePackages` 에서만 오므로
# 이 mod 는 그 mod 가 켜진 호스트에서만 의미가 있다(아래 assertion). 읽기는 일반 사용자 권한으로 sysfs 를 직접 읽는다.
#
# root 가 필요한 쓰기(msi-ec 의 shift_mode·cooler_boost, 배터리 충전 임계값)는 **시스템 템플릿 유닛 `embedctl-root@<동작>.service` 한 종류**로만 한다.
# 인스턴스 이름이 곧 동작이고(charge-<N>·mode-<turbo|comfort|eco>·boost-<on|off>), helper 가 이름을 엄격히 검증한다(embedlib.INSTANCE_RE).
# polkit 은 로컬 활성 세션 사용자의 `start` 만 이 유닛들에 허용한다 — 선례: hosts/msi-summit-me.nix 의 tlp-lid-closed/open 규칙(232행~).
# 결과는 /run/embedctl/last-<인스턴스>.json 으로 사용자 CLI 에 돌아온다(oneshot 이 끝나도 남도록 RuntimeDirectory 가 아니라 tmpfiles 로 만든다).
{mkMod, ...}:
mkMod __curPos "embedctl: MS-1592 노트북의 EC 상태(충전 상한·성능 모드·Cooler Boost) 도구" ({
  pkgs,
  config,
  ...
}: let
  # 본체·helper·ctlkit 을 한 디렉터리에 둔다(embedctl.py 와 embedhelper.py 는 같은 디렉터리의 embedlib·ctlkit 을 import).
  # `python3 -I`(격리 모드)에서는 스크립트 디렉터리가 sys.path 에 없으므로 두 파일이 스스로 HERE 를 추가한다.
  dir = pkgs.runCommand "embedctl-py" {} ''
    mkdir -p $out
    cp ${../../_tools/desktop/embedctl/embedctl.py} $out/embedctl.py
    cp ${../../_tools/desktop/embedctl/embedlib.py} $out/embedlib.py
    cp ${../../_tools/desktop/embedctl/embedhelper.py} $out/embedhelper.py
    cp ${../../_tools/desktop/embedctl/embedctlui.py} $out/embedctlui.py
    cp ${../../_tools/_lib/ctlkit/ctlkit.py} $out/ctlkit.py
    cp ${../../_tools/_lib/uikit/uikit.py} $out/uikit.py
  '';
  py = "${pkgs.python3}/bin/python3";
  pyUi = "${pkgs.python3.withPackages (ps: [ps.textual])}/bin/python3"; # TUI 만 textual 이 필요하다(CLI 와 root helper 는 표준 라이브러리만)
  embedctl = pkgs.writeShellScriptBin "embedctl" ''
    export EMBEDCTL_SYSTEMCTL="''${EMBEDCTL_SYSTEMCTL:-${pkgs.systemd}/bin/systemctl}"
    exec ${py} -I ${dir}/embedctl.py "$@"
  '';
  embedctlui = pkgs.writeShellScriptBin "embedctlui" ''
    export EMBEDCTL_SYSTEMCTL="''${EMBEDCTL_SYSTEMCTL:-${pkgs.systemd}/bin/systemctl}"
    exec ${pyUi} -I ${dir}/embedctlui.py "$@"
  '';
in {
  os = {
    # msi-ec 를 올리는 곳은 kernel-lockdown mod 뿐이다 — 없이 켜면 /sys/devices/platform/msi-ec 가 없어 embedctl 이 읽기도 쓰기도 못 한다(plan/embedctl-lockdown 결정 8).
    # 펌웨어가 msi-ec 허용 목록 밖이 되는 경우는 빌드로 못 잡으므로 embedctl 이 실행 때 게이트 `no_msi_ec` 로 이유를 밝힌다.
    assertions = [
      {
        assertion = config.mods.sys.services.kernel-lockdown.enable;
        message = "embedctl mod: msi-ec 커널 모듈은 kernel-lockdown mod 가 제공합니다. embedctl 을 켜려면 같은 호스트에서 kernel-lockdown 도 켜야 합니다(sysfs 로만 EC 를 다룹니다).";
      }
    ];

    environment.systemPackages = [embedctl embedctlui];

    systemd.tmpfiles.rules = ["d /run/embedctl 0755 root root -"];

    systemd.services."embedctl-root@" = {
      description = "embedctl root helper (%i)";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${py} -I ${dir}/embedhelper.py %i";
        NoNewPrivileges = true;
        PrivateNetwork = true;
        ProtectHome = true;
      };
    };

    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
        var unit = action.lookup("unit") || "";
        if (action.id == "org.freedesktop.systemd1.manage-units" &&
            action.lookup("verb") == "start" &&
            unit.indexOf("embedctl-root@") === 0 &&
            unit.slice(-8) === ".service" &&
            subject.local && subject.active) {
          return polkit.Result.YES;
        }
      });
    '';
  };
})
