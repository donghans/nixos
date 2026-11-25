{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  config,
  lib,
  ...
}: let
  # sbox 를 쓰는 호스트(incus-sbox 가 켜진 호스트)에서만 도구 신뢰 점검 알림·타이머를 둔다
  sboxHost = config.mods.sys.services.incus-sbox.enable;
  sboxDir = ../../../core/sbox; # 디렉터리째 스토어로 복사 — tools.py 가 옆의 tools.toml·probe.py 를 읽는다
  toolsPy = "${sboxDir}/tools.py";
in {
  hm = {
    # sbox 도구 신뢰 주기 점검(plan dev-sandbox-pilot §29-7, S57): 하루 한 번 깨어나 `tools.py periodic` 이 각 점검의 주기(CT 7일·키 지문 30일·교차검증은 crosscheck.toml)가
    # 지났을 때만 외부에 접속한다. 결과는 ~/.local/state/sbox/crosscheck.json → 위 waybar custom/trustcheck. ssh 관점은 BatchMode 라 암호를 묻지 않는다.
    # 끄기: 호스트 toml 의 incus-sbox 를 끄거나 이 두 블록을 지우고 nixup.
    systemd.user.services.sbox-trustcheck = lib.mkIf sboxHost {
      Unit.Description = "sbox tools trust periodic check (CT monitor, key pin, vantage cross-check)";
      Service = {
        Type = "oneshot";
        Environment = ["PATH=${lib.makeBinPath [pkgs.openssh pkgs.gnupg]}"];
        ExecStart = "${pkgs.python3}/bin/python3 ${toolsPy} periodic";
      };
    };
    systemd.user.timers.sbox-trustcheck = lib.mkIf sboxHost {
      Unit.Description = "sbox tools trust check schedule (daily)";
      Timer = {
        OnCalendar = "daily";
        RandomizedDelaySec = "1h";
        Persistent = true;
      };
      Install.WantedBy = ["timers.target"];
    };

    # sbox broker 의 키 주입 비밀 자동 복구(S64, pilot §29-81·82): 비밀은 broker ct 의 tmpfs 에만 있어 호스트 재부팅·broker 재시작 때 비워진다.
    # 2분마다 `sboxctl broker secret --if-missing` 이 broker 가 떠 있는데 비밀이 없을 때만 `donghans secret` 등록표에서 다시 넣는다(정상이면 아무것도 안 함).
    # DB(tailnet)에 닿지 못하면 실패로 남고 다음 주기에 다시 시도한다. 끄기: 호스트 toml 의 incus-sbox 를 끄거나 이 두 블록을 지우고 nixup.
    systemd.user.services.sbox-broker-secret = lib.mkIf sboxHost {
      Unit.Description = "sbox broker anthropic secret re-inject (only when missing)";
      Service = {
        Type = "oneshot";
        Environment = ["PATH=%h/.nix-profile/bin:/run/current-system/sw/bin"];
        ExecStart = "${pkgs.bash}/bin/bash %h/nixos/core/scripts/sboxctl broker secret --if-missing";
      };
    };
    systemd.user.timers.sbox-broker-secret = lib.mkIf sboxHost {
      Unit.Description = "sbox broker secret check (every 2 minutes)";
      Timer = {
        OnBootSec = "90s";
        OnUnitActiveSec = "2min";
      };
      Install.WantedBy = ["timers.target"];
    };

    # waybar 세션 시작
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "uwsm app -- sh -c 'sleep 2 && ${pkgs.waybar}/bin/waybar'"
    ];

    programs.waybar.enable = true;

    # waybar/config 내용
    programs.waybar.settings.mainBar = {
      layer = "top";
      position = "top";
      height = 24;

      margin-top = 0;
      margin-bottom = 0;
      margin-left = 0;
      margin-right = 0;
      spacing = 0;

      modules-left = ["hyprland/workspaces" "hyprland/submap"];
      modules-center = ["hyprland/window"];
      modules-right =
        ["tray"]
        # 도구 서명·망 교차검증의 주기 알림(sbox 도구 층): 기한이 지나거나 경고가 있을 때만 나타남(plan dev-sandbox-pilot §29-7)
        ++ lib.optionals sboxHost ["custom/trustcheck"]
        # 실패한 서비스가 있을 때만 나타나는 경고(notif health 가 1분마다 확인, 클릭하면 알림 센터의 문제 화면)
        ++ lib.optionals config.services.custom-notify-logger.enable ["custom/health"]
        ++ (
          # 가상 키보드 버튼은 2-in-1 호스트만, 배터리는 모든 노트북
          lib.optionals config.workspace.convertible ["custom/vkbsize" "custom/vkbmode" "custom/vkb"]
          ++ lib.optionals (config.workspace.type == "laptop") ["battery"]
        )
        ++ ["clock"];

      # 터치로 누를 수 있는 버튼들(터치스크린에는 우클릭/스크롤이 없어서 모두 단일 탭으로 동작)
      #  ⌨: 가상 키보드 접기/펴기 / ⧉: 하단 고정↔플로팅 / 크기(S·M·L): 탭하면 다음 크기. 크기·⧉ 는 키보드가 보일 때만 나타남
      #  세 버튼 모두 노트북 모드에서는 키보드가 떠 있을 때만 보이고 텐트/태블릿에서는 항상 보임(vkb waybar 가 빈 출력을 내면 모듈이 사라짐)
      # (vkb 가 상태를 바꾸거나 사용 모드가 바뀔 때만 waybar 에 신호(RTMIN+8)를 보내 다시 그리므로 폴링이 없음. 한/영 전환은 시스템 트레이의 fcitx5 아이콘과 키보드 안의 한/영 키)
      # `tools.py crosscheck-status` 는 상태 파일(~/.local/state/sbox/crosscheck.json)만 읽는다 — 정상이면 빈 텍스트라 모듈이 사라진다
      "custom/trustcheck" = {
        exec = "${pkgs.python3}/bin/python3 ${toolsPy} crosscheck-status";
        return-type = "json";
        interval = 3600;
        tooltip = true;
      };
      "custom/health" = {
        exec = "notif waybar";
        return-type = "json";
        interval = "once";
        signal = 9;
        on-click = "notif-open problems";
        tooltip = true;
      };
      "custom/vkb" = {
        exec = "vkb waybar";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb toggle";
        tooltip = true;
      };
      "custom/vkbsize" = {
        exec = "vkb waybar size";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb size cycle";
        tooltip = true;
      };
      "custom/vkbmode" = {
        exec = "vkb waybar mode";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb mode toggle";
        tooltip = true;
      };

      "hyprland/workspaces" = {
        format = "{name}";
        on-click = "activate";
        all-outputs = false;
        sort-by-number = true;
      };

      "hyprland/window" = {
        format = "{}";
        separate-outputs = true;
      };

      "battery" = {
        format = "{} %";
        states = {
          warning = 30;
          critical = 15;
        };
      };

      "tray" = {
        icon-size = 18;
        spacing = 4;
      };

      "clock" = {
        format = "{:%Y-%m-%d %H:%M}";
        tooltip-format = "{:%A, %B %d, %Y}";
      };
    };

    programs.waybar.style = builtins.readFile ../../_data/waybar/style.css;
  };
})
