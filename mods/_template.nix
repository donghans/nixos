# _template.nix — 새 모듈 작성 시 복사해서 사용
#
# 사용 방법:
#   1. 이 파일을 mods/<domain>/<name>.nix 로 복사
#   2. DESCRIPTION 을 실제 값으로 교체 (예: "Vivaldi browser")
#   3. os / hm 블록 작성 (불필요한 블록은 삭제)
#   4. mods/_preset/workstation.toml 또는 server.toml 에 기본값 추가
#      예: [mods.gui.apps]  vivaldi = false
#
# enable 옵션은 자동으로 추가됨 (__curPos → 파일 경로에서 option path 자동 유도).
# os/hm 블록에 plain attrset을 쓰면 mkIf cfg.enable 이 자동 적용됨.
# mkMerge 등이 필요하면 직접 사용 — 자동 감지로 그대로 통과됨.
{mkMod, ...}:
mkMod __curPos "<description>" ({
  cfg,
  pkgs,
  lib,
  unstable,
  ...
}: {
  # -- 추가 옵션 (enable 외, 불필요하면 삭제) --
  # options = {
  #   package = lib.mkPackageOption pkgs "<package-name>" {};
  # };

  # -- NixOS 시스템 설정 (mkIf cfg.enable 자동 적용) --
  # OS 설정이 없으면 이 블록 삭제
  os = {
    # environment.systemPackages = [ pkgs.<name> ];
    # services.<name>.enable = true;
  };

  # -- Home Manager 설정 (mkIf cfg.enable 자동 적용) --
  # HM 설정이 없으면 이 블록 삭제
  hm = {
    # home.packages = [ pkgs.<name> ];
    # programs.<name>.enable = true;
  };
})
