{mkPartOf, ...}:
mkPartOf "mods.gui" ({config, ...}: {
  hm = {
    programs.fuzzel.enable = true;

    programs.fuzzel.settings = {
      main = {
        font = "NanumGothicCoding:size=13";
        # hyprTerm은 _module.args로 전달되나 innerModule의 named arg로 받으면
        # 함수 호출 시 key set 강제평가로 순환 참조 발생 → config로 lazily 접근
        terminal = config._module.args.hyprTerm;
        # (목적: fuzzel로 실행하는 모든 앱을 uwsm 자체 scope로 분리)
        # (이유: systemd 자체 통합이 없는 네이티브 앱(Zed, kitty 등)은 이 prefix가 없으면
        #        Hyprland와 완전히 같은 cgroup에 눌러앉아 CPU/IO weight 분리가 무의미해짐.
        #        Chromium/Electron계(Vivaldi, Slack)는 자체적으로 scope를 옮기므로 영향 없음)
        launch-prefix = "uwsm app -- ";
        width = 80;
        lines = 40;
        horizontal-pad = 20;
        dpi-aware = "no";
        show-icons = "yes";
        icon-theme = "Papirus-Dark";
      };

      colors = {
        background = "000000ff";
        text = "ffffffff";
        match = "cb4b16ff";
        selection = "268bd2ff";
        selection-text = "ffffffff";
        border = "002b36ff";
      };

      border = {
        width = 1;
        radius = 0;
      };
    };
  };
})
