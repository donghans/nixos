# [working-refactor] 해당 구문은 before-refactor/dev/beelink-ser7-co/home.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{...}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [../../mods/devel/base/default.nix];

  # (목적: 5분간 미입력 시 자동 잠금)
  services.hypridle.settings.listener = [
    {
      timeout = 300; # 5분간 미입력 시
      on-timeout = "loginctl lock-session";
    }
  ];
}
