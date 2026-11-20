# NixOS VM 시험 모음(이 폴더). 무겁다(KVM 필요, 시험당 약 3~5분, lanzaboote 소스를 받아 온다) —
# 그래서 mods/_tools/run-tests.sh 의 기본 묶음에는 넣지 않고 필요할 때 손으로 돌린다.
#
#   cd core/scripts/tests/vm && nix-build default.nix -A positive --no-out-link             # 저장소(core/flake.lock)의 nixpkgs — 실제 호스트와 같은 systemd
#   cd core/scripts/tests/vm && nix-build default.nix -A negative --no-out-link
#   cd core/scripts/tests/vm && nix-build default.nix -A doctor --no-out-link               # nixseal doctor(선언 ↔ 실제)
#   cd core/scripts/tests/vm && nix-build default.nix -A positive-lzpkgs --no-out-link      # lanzaboote 의 nixpkgs(더 새로운 systemd 261.x)로(올리기 전 확인)
#
# lanzaboote 모듈·시험 모듈(common/·fixtures/)은 core/flake.lock 이 고정한 lanzaboote 리비전을 쓴다.
let
  lock = builtins.fromJSON (builtins.readFile ../../../flake.lock);
  ln = lock.nodes.lanzaboote.locked;
  lz = builtins.getFlake "github:${ln.owner}/${ln.repo}/${ln.rev}";
  # positive/negative 는 저장소(core/flake.lock)의 nixpkgs 로 게스트 전체를 만들어 실제 호스트와 같은 systemd(260.x)를 시험한다.
  # (게스트 systemd 만 바꾸는 방식은 안 된다 — 새 nixpkgs 의 NixOS 모듈이 260.1 에 없는 유닛(systemd-pcrlogin@)을 참조한다.)
  pn = lock.nodes.${lock.nodes.root.inputs.nixpkgs}.locked;
  repoPkgs = import (builtins.fetchTree {
    type = "github";
    inherit (pn) owner repo rev narHash;
  }) {system = "x86_64-linux";};
  lzPkgs = lz.inputs.nixpkgs.legacyPackages.x86_64-linux;
  # 저장소 nixpkgs(26.05)와 틀(lanzaboote 의 common/)의 차이를 메우는 shim: image.repart.enable 옵션(26.05 에는 없음)·OVMF.
  repoShim = {lib, pkgs, ...}: {
    options.image.repart.enable = lib.mkOption {type = lib.types.bool; default = true;};
    # 26.05 에서는 TPM(TCG)·Secure Boot 가 들어 있는 OVMFFull 을 명시해야 한다(새 nixpkgs 는 기본 OVMF 에 들어 있다)
    config.virtualisation = {
      efi.OVMF = pkgs.OVMFFull;
      useSecureBoot = true;
    };
  };
  mk = pkgs: shim: scenario:
    pkgs.testers.runNixOSTest {
      imports = [./sb-pcrlock.nix];
      _module.args = {inherit lz scenario;};
      globalTimeout = 15 * 60;
      extraBaseModules = {imports = [lz.nixosModules.lanzaboote] ++ lz.inputs.nixpkgs.lib.optional shim repoShim;};
    };
  # recover 시험: ISO 와 같은 nixseal 래퍼 + lanzaboote 가 깔린 대상 시스템(저장소 nixpkgs 로 평가)
  mkRecover = scenario: let
    pkgs = repoPkgs;
    target =
      (import "${pkgs.path}/nixos" {
        system = "x86_64-linux";
        configuration = {lib, ...}: {
          imports = [lz.nixosModules.lanzaboote];
          boot.loader.systemd-boot.enable = lib.mkForce false;
          boot.loader.efi.canTouchEfiVariables = false;
          boot.lanzaboote = {
            enable = true;
            pkiBundle = "/var/lib/sbctl";
          };
          boot.initrd.systemd.enable = true;
          boot.initrd.luks.devices.cryptroot.device = "/dev/disk/by-uuid/aaaaaaaa-0000-4000-8000-000000000001";
          fileSystems."/" = {
            device = "/dev/mapper/cryptroot";
            fsType = "btrfs";
            options = ["subvol=@"];
          };
          fileSystems."/boot" = {
            device = "/dev/disk/by-uuid/1234-ABCD";
            fsType = "vfat";
          };
          system.stateVersion = "26.05";
        };
      }).config.system.build.toplevel;
    nixseal = import ../../../lib/nixseal-iso.nix {
      inherit pkgs;
      script = ../../nixseal.py;
    };
  in
    pkgs.testers.runNixOSTest {
      imports = [./sb-recover.nix];
      _module.args = {inherit lz nixseal target scenario;};
      globalTimeout = 20 * 60;
    };
in {
  recover = mkRecover "run";
  recoverprep = mkRecover "prep"; # 대상 디스크 이미지 준비만(ISO 부팅 시험용)
  positive = mk repoPkgs true "positive";
  negative = mk repoPkgs true "negative";
  esp = mk repoPkgs true "esp";
  tpmlogin = mk repoPkgs true "tpmlogin"; # 봉인된 계정 비밀번호로 부팅 직후 로그인·키링 자동 해제(plan/boot-doctor-keyring §11-B)
  doctor = mk repoPkgs true "doctor"; # nixseal doctor 가 실제 장치·TPM·펌웨어에서 선언과 어긋남을 잡는지(plan/boot-doctor-keyring)
  # lanzaboote 의 nixpkgs 가 가진 더 새로운 systemd(261.x)로도 — 앞으로 nixpkgs 를 올릴 때 미리 확인
  positive-lzpkgs = mk lzPkgs false "positive";
  negative-lzpkgs = mk lzPkgs false "negative";
}
