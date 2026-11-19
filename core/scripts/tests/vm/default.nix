# NixOS VM 시험 모음(이 폴더). 무겁다(KVM 필요, 시험당 약 3~5분, lanzaboote 소스를 받아 온다) —
# 그래서 mods/_tools/run-tests.sh 의 기본 묶음에는 넣지 않고 필요할 때 손으로 돌린다.
#
#   cd core/scripts/tests/vm && nix-build default.nix -A positive --no-out-link             # 저장소(core/flake.lock)의 nixpkgs — 실제 호스트와 같은 systemd
#   cd core/scripts/tests/vm && nix-build default.nix -A negative --no-out-link
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
in {
  positive = mk repoPkgs true "positive";
  negative = mk repoPkgs true "negative";
  esp = mk repoPkgs true "esp";
  # lanzaboote 의 nixpkgs 가 가진 더 새로운 systemd(261.x)로도 — 앞으로 nixpkgs 를 올릴 때 미리 확인
  positive-lzpkgs = mk lzPkgs false "positive";
  negative-lzpkgs = mk lzPkgs false "negative";
}
