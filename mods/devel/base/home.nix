# [working-refactor] 해당 구문은 before-refactor/lib/developer.home.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{...}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [
    ../../gui/core/home.nix
    ../toolchains/devbox.nix
    ../toolchains/fvm.nix
    ../jetbrains/default.nix
    ../toolchains/node.nix
    ../toolchains/python.nix
  ];
}
