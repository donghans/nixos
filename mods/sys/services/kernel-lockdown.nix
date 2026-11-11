{mkMod, ...}:
# unstable 커널로 바꾸고, lockdown 에서도 커널 모듈이 올라오도록 커널 이미지를 다시 만들어 **부팅 항목이 그 이미지를 쓰게 한다** (plan boot-security S1·S3a).
#  - 지금(stable 26.05)의 NixOS 커널은 lockdown 이 컴파일되지 않아 `/sys/kernel/security/lockdown` 이 없다 (2026-11-09 `/proc/config.gz` 확인).
#  - unstable 커널은 lockdown 이 들어 있지만, **기본 이미지(`$out/kernel`)로 lockdown 을 올리면 모든 모듈이 거부된다**
#    (`Lockdown: …: unsigned module loading is restricted`, `Failed to insert module … Operation not permitted`; 2026-11-10 VM 시험).
#    nixpkgs 는 모듈마다 kmodigest 인증서를 만들어 `modules.cer` 로 모으고, 이를 커널 이미지에 끼워 넣어(`rebuildImage`) 검증이 되게 한다.
#    NixOS 모듈이 이를 자동으로 쓰지는 않아서, nixpkgs 시험(`nixos/tests/kernel-module-verification.nix`)과 같이 이미지를 다시 만든다. 커널 컴파일은 다시 하지 않는다(보존된 vmlinux 에 인증서만 끼움).
#  - **부트로더가 읽는 값은 `$out/kernel` 이 아니라 `boot.json`(bootspec)의 `org.nixos.bootspec.v1.kernel` 이다**(systemd-boot-builder.py·lanzaboote 모두).
#    그 값은 nixpkgs 의 bootspec.nix 가 `${kernelPackages.kernel}/${kernelFile}` 로 고정해 만들고 덮어쓰는 옵션이 없으며, `systemBuilderCommands` 는 boot.json 을 쓰는 `boot.bootspec.writer` **보다 먼저** 실행된다.
#    그래서 `writer`(internal 옵션) 를 기본 생성기 + jq 로 `kernel` 값 교체로 덮어쓴다. 교체 뒤 값이 기대와 다르면 빌드를 실패시킨다(nixpkgs 변경 대비). 안 A (plan §6-2f).
#  - 이 mod 는 커널 패키지·이미지와 initrd 에서 lockdown 을 올리는 서비스(lockdown-engage-initrd)를 다룬다. `lsm=lockdown,...` 인자는 호스트가 넣는다 (hosts/msi-summit-me.nix 의 kernelBase; lockdown=integrity 는 인자로 넣지 않는다).
#  - 2026-11-11 시험(specialisation) 통과 뒤 기본 구성으로 옮겼다. 이 mod 를 켜는 호스트는 `lsm=` 에 lockdown 이 있어야 하고, psr-force-initrd 같은 debugfs 쓰기 initrd 서비스는 `lockdown-engage-initrd` 보다 먼저 끝나야 한다(After 로 순서만 건다).
#  - rolling 락이라 `nixup` 마다 unstable 리비전이 바뀌어 커널 패치 버전이 달라지거나 바이너리 캐시에 없으면 로컬 빌드가 필요할 수 있다 (plan §9).
mkMod __curPos "unstable 커널 + 모듈 인증서를 넣은 이미지 (lockdown 시험용)" ({
  unstable,
  config,
  options,
  lib,
  pkgs,
  ...
}: let
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
  imageFile = "${finalKernel}/${target}";
  jq = "${pkgs.buildPackages.jq}/bin/jq";
in {
  os = {
    boot.kernelPackages = lib.mkForce unstable.linuxPackages;
    # 시험(2026-11-11): lockdown 에서 쓸 수 있는 쿨러 제어용 out-of-tree msi-ec (embedctl 은 debugfs 라 lockdown 에서 막힘). 인증서 문제는 위 certTree.
    boot.extraModulePackages = [config.boot.kernelPackages.msi-ec];
    boot.kernelModules = ["msi-ec"]; # 외부 모듈은 DMI 별칭이 없어 자동으로 안 올라온다(2026-11-11 실기: modprobe 하면 lockdown 에서도 서명 검증 통과·로드됨)
    system.systemBuilderCommands = lib.mkAfter ''
      ln -sf -- ${lib.escapeShellArg imageFile} $out/kernel
    '';
    # 부트로더(systemd-boot·lanzaboote)가 읽는 boot.json 의 kernel 값을 인증서 이미지로 바꾼다 (S3a 안 A).
    # 올리는 시점 = **initrd**, 디스크 해제(LUKS 입력)·루트 마운트보다 먼저 (S3b 승격 2026-11-12; 시험 specialisation 으로 initrd 4.58초에 올라옴을 실기 확인).
    # debugfs 를 쓰는 initrd 서비스(호스트의 psr-force-initrd 등)는 이 서비스보다 먼저 끝나야 한다(`before = ["lockdown-engage-initrd.service"]` 로 순서만 건다. Requires 는 쓰지 않아 실패해도 lockdown 은 올라간다).
    # 한 번 올리면 재부팅 전까지 내릴 수 없다. 커널 시작~이 서비스 구간만 보호가 없다.
    # initrd 의 systemd 에는 securityfs 마운트 유닛이 없어 스크립트가 직접 마운트한다. 유닛 스크립트가 참조한 store 경로의 프로그램은 initrd 에 자동 포함되지 않으므로
    # initrd 의 `/bin` 에 있는 `mount`(util-linux-minimal)를 이름으로 부르고 grep 대신 셸 내장으로 확인한다.
    boot.initrd.systemd.enable = true;
    boot.initrd.systemd.services.lockdown-engage-initrd = {
      description = "Engage kernel lockdown (integrity) in initrd";
      wantedBy = ["initrd.target"];
      before = ["cryptsetup-pre.target" "initrd-root-device.target" "sysroot.mount"];
      unitConfig.DefaultDependencies = false;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        /bin/mount -t securityfs securityfs /sys/kernel/security || true
        echo integrity > /sys/kernel/security/lockdown
        read -r state < /sys/kernel/security/lockdown
        case "$state" in *"[integrity]"*) ;; *) echo "lockdown is not integrity: $state" >&2; exit 1 ;; esac
      '';
    };
    boot.bootspec.writer = lib.mkForce (options.boot.bootspec.writer.default
      + ''

        ${jq} --arg k ${lib.escapeShellArg imageFile} '."org.nixos.bootspec.v1".kernel = $k' $out/boot.json > $out/boot.json.patched
        mv $out/boot.json.patched $out/boot.json
        if [ "$(${jq} -r '."org.nixos.bootspec.v1".kernel' $out/boot.json)" != ${lib.escapeShellArg imageFile} ]; then
          echo "kernel-lockdown: boot.json 의 kernel 교체에 실패했다(nixpkgs 의 bootspec 생성 방식이 바뀌었을 수 있다)" >&2
          exit 1
        fi
      '');
  };
})
