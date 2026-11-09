# embedctl — MSI Summit E16Flip A12UDT(보드 MS-1592) 전용: EC 상태(충전 상한·성능 모드·Cooler Boost)를 허용 목록으로 읽고 다루는 CLI.
# 본체는 mods/_tools/desktop/embedctl/ (README.md), 설계·검증은 ctx `plan/embedctl-구현`.
# 기종 전용이라 모든 노트북에 깔지 않고 호스트 toml 의 `[mods.gui.apps] embedctl = true` 로만 켠다.
#
# root 가 필요한 EC 접근(MSI WMI debugfs 읽기·쓰기, sysfs 충전 상한 쓰기)은 **시스템 템플릿 유닛 `embedctl-root@<동작>.service` 한 종류**로만 한다.
# 인스턴스 이름이 곧 동작이고(status·charge-<N>·mode-<…>·boost-<…>), helper 가 이름을 엄격히 검증한다(embedlib.INSTANCE_RE).
# polkit 은 로컬 활성 세션 사용자의 `start` 만 이 유닛들에 허용한다 — 선례: hosts/msi-summit-me.nix 의 tlp-lid-closed/open 규칙(232행~).
# 결과는 /run/embedctl/last-<인스턴스>.json 으로 사용자 CLI 에 돌아온다(oneshot 이 끝나도 남도록 RuntimeDirectory 가 아니라 tmpfiles 로 만든다).
{mkMod, ...}:
mkMod __curPos "embedctl: MS-1592 노트북의 EC 상태(충전 상한·성능 모드·Cooler Boost) 도구" ({pkgs, ...}: let
  # 본체·helper·ctlkit 을 한 디렉터리에 둔다(embedctl.py 와 embedhelper.py 는 같은 디렉터리의 embedlib·ctlkit 을 import).
  # `python3 -I`(격리 모드)에서는 스크립트 디렉터리가 sys.path 에 없으므로 두 파일이 스스로 HERE 를 추가한다.
  dir = pkgs.runCommand "embedctl-py" {} ''
    mkdir -p $out
    cp ${../../_tools/desktop/embedctl/embedctl.py} $out/embedctl.py
    cp ${../../_tools/desktop/embedctl/embedlib.py} $out/embedlib.py
    cp ${../../_tools/desktop/embedctl/embedhelper.py} $out/embedhelper.py
    cp ${../../_tools/_lib/ctlkit/ctlkit.py} $out/ctlkit.py
  '';
  py = "${pkgs.python3}/bin/python3";
  embedctl = pkgs.writeShellScriptBin "embedctl" ''
    export EMBEDCTL_SYSTEMCTL="''${EMBEDCTL_SYSTEMCTL:-${pkgs.systemd}/bin/systemctl}"
    exec ${py} -I ${dir}/embedctl.py "$@"
  '';
in {
  os = {
    environment.systemPackages = [embedctl];

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
