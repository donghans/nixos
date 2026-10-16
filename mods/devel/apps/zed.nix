{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Zed editor" ({
  unstable,
  lib,
  pkgs,
  ...
}: {
  hm = {
    home.packages = [unstable.zed-editor];

    # settings.json 은 Zed 가 직접 다시 쓰는 파일이라 통째로 선언하지 않고 키 하나만 활성화 때 맞춘다.
    #  - cli_default_open_behavior: new_window 면 `zeditor <폴더/파일>`(Thunar "Open With", 터미널)이 항상 새 창으로 열림.
    #    existing_window(이전 값)는 열려 있는 창을 그 폴더로 바꿔 버렸음(빈 프로젝트 창이 시험 폴더로 대체되는 것을 확인).
    home.activation.zedSettings = lib.hm.dag.entryAfter ["writeBoundary"] ''
      conf="$HOME/.config/zed/settings.json"
      if [ -z "''${DRY_RUN:-}" ] && [ -f "$conf" ]; then
        if ${pkgs.gnugrep}/bin/grep -q '"cli_default_open_behavior"' "$conf"; then
          ${pkgs.gnused}/bin/sed -i 's|"cli_default_open_behavior": *"[a-z_]*"|"cli_default_open_behavior": "new_window"|' "$conf"
        else
          ${pkgs.gnused}/bin/sed -i '0,/^{/s|^{|{\n  "cli_default_open_behavior": "new_window",|' "$conf"
        fi
      fi
    '';
  };
})
