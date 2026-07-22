/*
  Tailpass(Headscale 전용 팀 비밀 관리자, /home/donghans/tailpass) daemon/authagent/App.

  flake input이 아니라 mods/_data/tailpass/에 vendoring된 사본을 쓴다 — nixup은 nix를
  --impure 없이 path:$BUILD_DIR로 호출하는데, tailpass 저장소를 flake input으로 끌어오면
  (a) 순정 절대경로 참조는 pure eval에서 거부되고 (b) git+file:로 끌어와도 target/(39GB)
  때문에 별도 처리가 필요해서, 코드+`.deb`를 그냥 로컬로 복사해 mods/ 트리 안에 두는 쪽을
  택했다(mods/_data 컨벤션과 동일). tailpass 쪽 deploy/nix/*.nix가 바뀌면
  mods/_data/tailpass/를 수동으로 다시 복사해야 한다 — .deb는 .gitignore 처리됨.
*/
{ mkMod, forOS ? false, lib, pkgs, ... }:

let
  tailpassApp = pkgs.callPackage ../../_data/tailpass/package.nix {
    debSrc = ../../_data/tailpass/tailpass.deb;
  };

  # mods/는 NixOS·Home Manager 양쪽 트리에 공용으로 imports되므로(recursiveImportDir),
  # tailpass 모듈(environment.etc/services.dbus/systemd.services/users.users 등 NixOS
  # 전용 옵션 사용)은 forOS=true일 때만 imports에 넣어야 한다 — HM 컨텍스트에 그대로
  # 섞이면 "option `environment' does not exist" 식으로 깨진다(core/lib/mods.nix
  # mkNamedMod 주석의 "sub-module imports가 필요하면 외부 모듈에서 직접 선언" 패턴).
  baseMod = mkMod __curPos "Tailpass (Headscale 전용 팀 비밀 관리자)" ({ cfg, config, ... }: {
    os = {
      services.tailpass-daemon = {
        enable = true;
        users = [ config.workspace.username ];
      };
      services.tailpass-authagent.enable = true;
      environment.systemPackages = [ tailpassApp ];
    };
    # xdg.mimeApps.enable(mods/gui/base/xdg.nix)로 ~/.config/mimeapps.list가 HM
    # 관리 심볼릭 링크(nix store, 읽기전용)라, tailpass-app이 런타임에
    # `xdg-mime default`로 tailpass:// 스킴을 스스로 등록하려 하면
    # "Read-only file system"으로 실패한다(tauri-plugin-deep-link가 내부적으로
    # xdg-mime을 셸아웃 — deploy/nix/package.nix 주석 참조, 실패해도 앱 실행은
    # 안 막는 경고일 뿐). HM 쪽에서 선언적으로 등록해 실질적으로 동작하게 한다.
    hm = {
      xdg.mimeApps.defaultApplications."x-scheme-handler/tailpass" = [ "Tailpass.desktop" ];
    };
  });
in
{
  imports = baseMod.imports
    ++ lib.optional forOS (import ../../_data/tailpass/modules { tailpassPackage = tailpassApp; });
}
