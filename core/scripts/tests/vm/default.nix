# NixOS VM 시험 모음(이 폴더). 무겁다(KVM 필요, 시험당 약 3~5분, lanzaboote 소스를 받아 온다) —
# 그래서 mods/_tools/run-tests.sh 의 기본 묶음에는 넣지 않고 필요할 때 손으로 돌린다.
#
#   cd core/scripts/tests/vm && nix-build default.nix -A positive --no-out-link
#   cd core/scripts/tests/vm && nix-build default.nix -A negative --no-out-link
#
# lanzaboote·nixpkgs 는 저장소의 core/flake.lock 이 고정한 lanzaboote 리비전과 그 flake 가 쓰는 nixpkgs 를 쓴다
# (lanzaboote 의 시험 모듈 common/·fixtures/ 를 그대로 재사용하므로 그쪽 시험이 통과하는 조합이어야 한다).
let
  lock = builtins.fromJSON (builtins.readFile ../../../flake.lock);
  n = lock.nodes.lanzaboote.locked;
  lz = builtins.getFlake "github:${n.owner}/${n.repo}/${n.rev}";
  pkgs = lz.inputs.nixpkgs.legacyPackages.x86_64-linux;
  mk = scenario: pkgs.testers.runNixOSTest {
    imports = [ ./sb-pcrlock.nix ];
    _module.args = { inherit lz scenario; };
    globalTimeout = 15 * 60;
    extraBaseModules = { imports = [ lz.nixosModules.lanzaboote ]; };
  };
in
{
  positive = mk "positive";
  negative = mk "negative";
}
