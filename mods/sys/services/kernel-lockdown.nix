{mkMod, ...}:
# unstable 커널로 바꾸고, lockdown(integrity)에서도 커널 모듈이 올라오도록 커널 이미지를 다시 만든다 (plan boot-security S1; 아직 시험 단계).
#  - 지금(stable 26.05)의 NixOS 커널은 lockdown 이 컴파일되지 않아 `/sys/kernel/security/lockdown` 이 없다 (2026-11-09 `/proc/config.gz` 확인).
#  - unstable 커널은 lockdown 이 들어 있지만, **기본 이미지(`$out/kernel`)로 `lockdown=integrity` 부팅하면 모든 모듈이 거부된다**
#    (`Lockdown: …: unsigned module loading is restricted`, `Failed to insert module … Operation not permitted`; 2026-11-10 VM 시험).
#    nixpkgs 는 모듈마다 kmodigest 인증서를 만들어 `modules.cer` 로 모으고, 이를 커널 이미지에 끼워 넣어(`rebuildImage`) 검증이 되게 한다.
#    NixOS 모듈이 이를 자동으로 쓰지는 않아서, nixpkgs 시험(`nixos/tests/kernel-module-verification.nix`)과 같이 `$out/kernel` 을 다시 만든 이미지로 바꾼다.
#  - 이 mod 는 커널 패키지와 이미지만 다룬다. `lsm=lockdown,...`·`lockdown=integrity` 인자는 호스트가 kernelParams 목록을 통째로 지정하므로 호스트에서 넣는다
#    (hosts/msi-summit-me.nix 의 specialisation.lockdown-test).
#  - 시험은 호스트에서 specialisation 안에서만 이 mod 를 켠다. 기본 부팅 항목은 바뀌지 않는다.
#  - rolling 락이라 `nixup` 마다 unstable 리비전이 바뀌어 커널 패치 버전이 달라지거나 바이너리 캐시에 없으면 로컬 빌드가 필요할 수 있다 (plan §9).
mkMod __curPos "unstable 커널 + 모듈 인증서를 넣은 이미지 (lockdown 시험용)" ({
  unstable,
  config,
  lib,
  pkgs,
  ...
}: {
  os = {
    boot.kernelPackages = lib.mkForce unstable.linuxPackages;
    # 시험(2026-11-11): lockdown 에서 쓸 수 있는 쿨러 제어용 out-of-tree msi-ec (embedctl 은 debugfs 라 lockdown 에서 막힘). 인증서 문제는 아래 주석.
    boot.extraModulePackages = [config.boot.kernelPackages.msi-ec];
    system.systemBuilderCommands = let
      kp = config.boot.kernelPackages;
      inherit (kp.kernel) target;
      ver = kp.kernel.modDirVersion;
      # 외부 모듈(extraModulePackages)을 넣으면 NixOS 가 합친 modulesTree 에는 modules.cer 가 없다(2026-11-11 빌드 실패: `modules.cer: No such file`).
      # nixpkgs 의 커널 makeFlags 는 외부 모듈도 kmodigest 로 서명해 `<모듈>.ko.cer` 를 남기므로, 커널의 modules.cer 뒤에 그 인증서들을 이어 붙인 트리를 만들어 넘긴다.
      certTree = pkgs.runCommand "modules-cert-tree-${ver}" {} ''
        d=$out/lib/modules/${ver}
        mkdir -p $d
        cat ${lib.getOutput "modules" kp.kernel}/lib/modules/${ver}/modules.cer > $d/modules.cer
        for m in ${lib.concatStringsSep " " config.boot.extraModulePackages}; do
          find "$m/lib/modules" -name '*.ko.cer' | sort | xargs -r cat >> $d/modules.cer
        done
      '';
      finalKernel = kp.rebuildImage {
        inherit target;
        modulesTree = certTree;
      };
    in
      lib.mkAfter ''
        ln -sf -- ${lib.escapeShellArg "${finalKernel}/${target}"} $out/kernel
      '';
  };
})
