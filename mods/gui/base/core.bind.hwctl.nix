{
  mkPartOf,
  lib,
  ...
}: let
  base = mkPartOf "mods.gui" ({
    pkgs,
    lib,
    config,
    ...
  }: let
    # == Hardware Control Scripts ==
    # 순수 쉘 스크립트 본문은 mods/_tools/desktop/hwctl/*.sh (자리표시자 목록은 그 폴더의 README.md).
    # `@이름@` 만 치환한다(replaceVars 는 wpctl 예약어 @DEFAULT_AUDIO_SINK@ 때문에 못 씀).
    hwctlDir = ../../_tools/desktop/hwctl;
    hwctlSh = name: subst: builtins.replaceStrings (builtins.attrNames subst) (builtins.attrValues subst) (builtins.readFile (hwctlDir + "/${name}.sh"));
    notifySend = "${pkgs.libnotify}/bin/notify-send";

    # 볼륨 조절 및 알림 스크립트
    volumeControl = pkgs.writeShellScriptBin "vol-control" (hwctlSh "vol-control" {
      "@wpctl@" = "${pkgs.wireplumber}/bin/wpctl";
      "@notify_send@" = notifySend;
    });

    # 밝기 조절 및 알림 스크립트
    brightnessControl = pkgs.writeShellScriptBin "brt-control" (hwctlSh "brt-control" {
      "@brightnessctl@" = "${pkgs.brightnessctl}/bin/brightnessctl";
      "@notify_send@" = notifySend;
    });

    # 덮개를 닫으면 화면을 끄고(백라이트 0), 열면 원래 밝기로 복원. dpms(화면 출력 끄기/켜기)는 쓰지 않는다:
    # 이 기기(i915 + Hyprland 0.55)에서 `dpms enable` 뒤에 화면이 다시 켜지지 않고 까맣게 남아(커널은 On, 백라이트 정상) hyprlock 이 떠 있어도 안 보였고
    # tty 를 옮겼다 와야 복구됐다(2026-10-17 잠금 없이도 재현). 백라이트만 쓰면 모드 재설정이 없다.
    # 밝기는 닫을 때 한 번만 저장(이미 0 이면 덮어쓰지 않음 → 닫힘이 두 번 와도 원래 밝기를 잃지 않음).
    lidScreen = pkgs.writeShellScriptBin "lid-screen" (hwctlSh "lid-screen" {
      "@brightnessctl@" = "${pkgs.brightnessctl}/bin/brightnessctl";
    });

    # 덮개 정책(사용 모드 허브의 소비자): 허브가 발행한 `posture get lid` 가 바뀌면 화면(백라이트)을 끄고 켜고, 호스트의 추가 명령(전원 프로필 등)을 실행한다.
    # 덮개 상태의 출처가 허브 한 곳이라 로그인/reload 후에도, 힌지 이벤트와 겹쳐도 같은 코드로 맞춰진다(마지막으로 적용한 값은 $XDG_RUNTIME_DIR/lid_applied 에 기록해 바뀔 때만 실행).
    # **잠금은 여기가 아니라 Hyprland 의 덮개 바인딩(아래 bindl)에 남겨 둔다**: 허브 데몬이 죽어 있어도 덮개를 닫으면 잠겨야 하므로 센서 파이프라인에 의존시키지 않는다.
    # 허브가 안 돌면 `posture get lid` 는 open 이라 화면은 켜진 쪽으로 복구된다.
    lidPolicy = pkgs.writeShellScriptBin "lid-policy" ''
      f="''${XDG_RUNTIME_DIR:-/tmp}/lid_applied"
      lid=$(${config.posture.cli}/bin/posture get lid)
      last=$(cat "$f" 2>/dev/null || echo open)
      [ "$lid" = "$last" ] && exit 0
      # 관측(observectl trace): 덮개 변화 처리 전체를 하나의 구간으로 남긴다(화면 끄기/켜기 + 전원 프로필 명령). observe-emit 이 없으면 건너뜀.
      tok=$(observe-emit span-begin lid-policy apply "lid=$lid" 2>/dev/null) || tok=""
      if [ "$lid" = closed ]; then
        ${lidScreen}/bin/lid-screen off
        ${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd != "") "${config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd} || ${pkgs.util-linux}/bin/logger -t lid-policy \"추가 명령 실패(닫힘)\""}
      else
        ${lidScreen}/bin/lid-screen on
        ${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd != "") "${config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd} || ${pkgs.util-linux}/bin/logger -t lid-policy \"추가 명령 실패(열림)\""}
      fi
      echo "$lid" > "$f"
      [ -n "$tok" ] && observe-emit span-end "$tok" >/dev/null 2>&1
      ${pkgs.util-linux}/bin/logger -t lid-policy "lid=$lid"
    '';

    # 터치패드/터치스크린 토글 (Laptop 전용). 장치를 직접 만지지 않는다: **수동 상태 파일만 뒤집고** 적용은 정책(hypr-input-policy)에 맡긴다.
    # (장치 선택·적용·상태 파일 기본값이 정책 한 곳에만 있도록: 예전에는 토글 두 개와 정책이 각자 같은 일을 했음)
    # mkToggle 인자: bin=스크립트 이름, label=알림 제목, file=수동 상태 파일 이름, field=`hypr-input-policy --print` 출력에서 현재 값의 필드 번호(터치패드 4 / 터치스크린 5), lockedMsg=텐트/태블릿에서 눌렀을 때 안내
    mkToggle = {
      bin,
      label,
      file,
      field,
      lockedMsg,
    }:
      pkgs.writeShellScriptBin bin (hwctlSh "toggle" {
        "@posture@" = "${config.posture.cli}/bin/posture";
        "@notify_send@" = notifySend;
        "@input_policy@" = "${inputPolicy}/bin/hypr-input-policy";
        "@bin@" = bin;
        "@label@" = label;
        "@file@" = file;
        "@field@" = toString field;
        "@locked_msg@" = lockedMsg;
      });
    toggleTouchpad = mkToggle {
      bin = "hypr-toggle-touchpad";
      label = "Touchpad";
      file = "touchpad_enabled";
      field = 4;
      lockedMsg = "텐트/태블릿 모드에서는 꺼짐으로 고정돼 있습니다 (힌지를 열면 직접 조절 가능)";
    };
    # (펜(stylus)은 그대로 둠)
    toggleTouchscreen = mkToggle {
      bin = "hypr-toggle-touchscreen";
      label = "Touchscreen";
      file = "touchscreen_enabled";
      field = 5;
      lockedMsg = "텐트/태블릿 모드에서는 켜짐으로 고정돼 있습니다 (힌지를 열면 직접 조절 가능)";
    };

    # 외부 키보드 판정/감시 CLI (mods/_tools/desktop/external-keyboard/extkbd.py). 도구 경로를 고정해 서비스 PATH 에 기대지 않는다.
    # (감시가 다시 실행할 정책 경로는 정책이 이 CLI 를 참조하므로 순환을 피하려 서비스 쪽 환경 변수 EXTKBD_POLICY 로 준다)
    extkbdCli = pkgs.writeShellScriptBin "extkbd" ''
      export EXTKBD_UDEVADM=${pkgs.systemd}/bin/udevadm EXTKBD_BUSCTL=${pkgs.systemd}/bin/busctl EXTKBD_GDBUS=${lib.getExe' pkgs.glib "gdbus"}
      exec ${pkgs.python3}/bin/python3 -I ${../../_tools/desktop/external-keyboard/extkbd.py} "$@"
    '';

    # 내장 키보드 이름(호스트가 지정). 비어 있으면 정책이 키보드를 건드리지 않는다(알려지지 않은 기기에서 키보드를 잘못 끄지 않도록).
    kbName = config.wayland.windowManager.hyprland.internalKeyboardName;
    tsUsb = config.wayland.windowManager.hyprland.touchscreenUsbId;

    # 입력 장치(내장 키보드/터치패드/터치스크린)의 켜짐/꺼짐 정책. 사용 모드(힌지 각도)는 `posture get mode`(core.posture.nix) 로 읽는다.
    #   laptop        : **마지막 수동 상태를 따름**(메뉴에서 정한 touchpad_enabled/touchscreen_enabled 파일, 없으면 터치패드 켬/터치스크린 끔), 키보드 켬
    #   tent, tablet  : **강제** 키보드 끔 / 터치패드 끔 / 터치스크린 켬 (접힌 채 등 쪽 키·패드가 눌리는 것 방지). 수동 상태 파일은 건드리지 않아서
    #                   노트북 모드로 돌아오면 원래 상태로 복원됨.
    #   안전장치: 사용 모드 서비스가 멈췄거나 파일이 없으면 posture CLI 가 laptop 을 돌려줌 → 키보드가 꺼진 채 남지 않음. 복구는 힌지를 190° 미만으로 여는 것.
    #   **외부 키보드(USB/2.4G/블루투스)가 연결돼 있으면 노트북 모드에서도 내장 키보드를 끔**(`extkbd present`; 키보드를 내장 키보드 위에 얹어 쓸 때의 오입력 방지).
    #   판정이 불확실하거나 `extkbd` 가 실패하면 "없음"(내장 키보드 켬)으로 본다. 설계/근거: mods/_tools/desktop/external-keyboard/README.md
    #   `--print` 는 판정만 출력("모드 각도 키보드 터치패드 터치스크린"), 장치는 건드리지 않음. 3번째 필드(키보드)가 곧 "내장 키보드가 켜져야 하는가"(외부 키보드 반영 후).
    #   장치를 건드리는 실행은 서로 겹치지 않게 잠금(flock)으로 직렬화한다: 힌지/로그인/reload(posture-apply)와 외부 키보드 감시(extkbd-watch)가 동시에 돌아도 낡은 판정이 나중에 덮어쓰지 않도록.
    # (장치 켜기/끄기(hl.device enabled)는 런타임 설정이라 hyprctl reload 때 초기화되므로 로그인/reload 때도 다시 적용 — posture-apply)
    inputPolicy = pkgs.writeShellScriptBin "hypr-input-policy" ''
      STATE_DIR="$HOME/.local/state/hypr"
      mkdir -p "$STATE_DIR"
      # 판정(읽기)부터 적용(쓰기)까지를 한 덩어리로 잠근다(`--print` 는 읽기만 하므로 제외). 30초 넘게 못 잡으면 그냥 진행(잠금 때문에 정책이 영영 안 도는 것보다 낫다)
      if [ "$1" != --print ]; then exec 9> "$STATE_DIR/policy.lock"; ${pkgs.util-linux}/bin/flock -w 30 9 || true; fi
      read -r mode angle lid < <(${config.posture.cli}/bin/posture get mode angle lid)   # (한 번에 읽음: 호출당 파이썬 시작 ~50ms)
      [ -n "$angle" ] || angle=-1
      # 외부 키보드 여부(내장 키보드를 지정한 호스트에서만 의미가 있다). 어떤 이유로든 실패하면 없음
      ext=false
      ${lib.optionalString (kbName != null) ''${extkbdCli}/bin/extkbd present && ext=true''}
      case "$mode" in
        tent|tablet) kb=false; tp=false; ts=true ;;
        *)
          kb=true
          [ "$ext" = true ] && kb=false
          tp=$(cat "$STATE_DIR/touchpad_enabled" 2>/dev/null || echo true)
          ts=$(cat "$STATE_DIR/touchscreen_enabled" 2>/dev/null || echo false)
          ;;
      esac
      if [ "$1" = --print ]; then echo "$mode $angle $kb $tp $ts"; exit 0; fi

      # set_enabled <대상 장치 jq 식> <true|false>
      set_enabled() {
        hyprctl devices -j | ${pkgs.jq}/bin/jq -r "$1" | while read -r dev; do
          [ -n "$dev" ] && hyprctl eval "hl.device({ name = \"$dev\", enabled = $2 })" > /dev/null
        done
      }
      # 터치스크린 USB 런타임 절전: 켜기 전에 깨우고(on), 끈 뒤에 재운다(auto). 끈 동안에는 터치로 깨울 일이 없어서 안전하다
      # (켜진 채 재우면 터치가 안 먹을 수 있어 그렇게는 하지 않음). **덮개를 닫았을 때도 재운다**: 닫으면 힌지가 359° 로 읽혀 tablet(터치 강제 켜짐)으로
      # 분류되지만 화면이 꺼져 터치할 수 없다. 덮개 스위치는 360° 로 접어도 open 그대로라 닫힘(closed)이면 실제로 닫은 것이다(mods/_tools/desktop/posture/README.md).
      # 쓸 수 없으면(권한/장치 없음) 조용히 넘어간다.
      usb_touch_power() {
        ${lib.optionalString (tsUsb != null) ''
        for d in /sys/bus/usb/devices/*; do
          [ "$(cat "$d/idVendor" 2>/dev/null):$(cat "$d/idProduct" 2>/dev/null)" = "${tsUsb}" ] && echo "$1" > "$d/power/control" 2>/dev/null
        done
      ''}
        return 0
      }
      ${lib.optionalString (kbName != null) ''set_enabled '.keyboards[] | select(.name == "${kbName}") | .name' "$kb"''}
      set_enabled '.mice[] | select(.name | contains("touchpad")) | .name' "$tp"
      touch_awake=false; { [ "$ts" = true ] && [ "$lid" != closed ]; } && touch_awake=true
      [ "$touch_awake" = true ] && usb_touch_power on
      set_enabled '.touch[]?.name' "$ts"
      [ "$touch_awake" = true ] || usb_touch_power auto

      # 모드가 바뀐 때만 알림(처음 실행은 조용히)
      last=$(cat "$STATE_DIR/hinge_last_mode" 2>/dev/null)
      if [ "$last" != "$mode" ]; then
        echo "$mode" > "$STATE_DIR/hinge_last_mode"
        if [ -n "$last" ]; then
          case "$mode" in
            tablet) msg="태블릿 모드 (힌지 $angle°): 키보드·터치패드 끔, 터치스크린 켬" ;;
            tent) msg="텐트 모드 (힌지 $angle°): 키보드·터치패드 끔, 터치스크린 켬" ;;
            *) if [ "$kb" = true ]; then
                 msg="노트북 모드 (힌지 $angle°): 키보드 켬, 터치패드·터치스크린은 마지막 설정으로 복원"
               else
                 msg="노트북 모드 (힌지 $angle°): 외부 키보드가 있어 내장 키보드는 끔, 터치패드·터치스크린은 마지막 설정으로 복원"
               fi ;;
          esac
          ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:hinge -u low "사용 모드" "$msg"
        fi
      fi
      ${lib.optionalString (kbName != null) ''
        # 외부 키보드가 생기거나 없어졌을 때만 알림(처음 실행은 조용히)
        last_ext=$(cat "$STATE_DIR/extkbd_last" 2>/dev/null)
        if [ "$last_ext" != "$ext" ]; then
          echo "$ext" > "$STATE_DIR/extkbd_last"
          if [ -n "$last_ext" ]; then
            if [ "$ext" = true ]; then msg="외부 키보드 연결됨 — 노트북 모드에서는 내장 키보드를 끕니다"; else msg="외부 키보드 없음 — 노트북 모드에서는 내장 키보드를 켭니다"; fi
            ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:extkbd -u low "외부 키보드" "$msg"
          fi
        fi
      ''}
      ${pkgs.util-linux}/bin/logger -t hypr-input-policy "mode=$mode angle=$angle lid=$lid ext=$ext keyboard=$kb touchpad=$tp touchscreen=$ts"
    '';

    # 로그인과 설정 reload 뒤에도 같은 정책을 다시 적용
    restoreInput = pkgs.writeShellScriptBin "hypr-restore-input" ''
      ${inputPolicy}/bin/hypr-input-policy
      ${pkgs.util-linux}/bin/logger -t hypr-restore-input "input device state restored"
    '';

    # 입력 장치 메뉴(터치패드/터치스크린): 터치패드 키를 누르면 wofi 로 표시. 항목 추가는 deviceMenuExtraEntries 옵션 사용
    # (화면 모드 전환은 별도: 화면 전환 키 SUPER+P / XF86Display → displayui, mods/gui/base/monitor-manager.nix)
    extraEntries = config.wayland.windowManager.hyprland.deviceMenuExtraEntries;
    deviceMenu = pkgs.writeShellScriptBin "hypr-device-menu" ''
      pkill -x '(.wofi-wrapped|wofi)' && exit 0

      labels=()
      cmds=()
      add() { labels+=("$1"); cmds+=("$2"); }
      # onoff <true|false>: 현재 상태(정책이 출력한 값)에 따른 라벨
      onoff() { [ "$1" = true ] && echo "끄기 (지금 켜짐)" || echo "켜기 (지금 꺼짐)"; }

      # 사용 모드에 따라: 노트북 모드는 직접 조절, 텐트/태블릿 모드는 고정(선택해도 바뀌지 않고 안내만)
      read -r mode angle kb tp ts < <(${inputPolicy}/bin/hypr-input-policy --print)
      case "$mode" in tablet) mname=태블릿 ;; tent) mname=텐트 ;; *) mname=노트북 ;; esac
      yn() { [ "$1" = true ] && echo 켜짐 || echo 꺼짐; }

      if [ "$mode" = laptop ]; then
        add "터치패드 $(onoff "$tp")" "${toggleTouchpad}/bin/hypr-toggle-touchpad"
        ${lib.concatMapStrings (e: "add ${lib.escapeShellArg e.label} ${lib.escapeShellArg e.command}\n        ") extraEntries}add "터치스크린 $(onoff "$ts")" "${toggleTouchscreen}/bin/hypr-toggle-touchscreen"
      else
        add "터치패드: $(yn "$tp") — $mname 모드(힌지 $angle°)에서 고정" "${toggleTouchpad}/bin/hypr-toggle-touchpad"
        ${lib.concatMapStrings (e: "add ${lib.escapeShellArg e.label} ${lib.escapeShellArg e.command}\n        ") extraEntries}add "터치스크린: $(yn "$ts") — $mname 모드(힌지 $angle°)에서 고정" "${toggleTouchscreen}/bin/hypr-toggle-touchscreen"
      fi

      sel=$(printf '%s\n' "''${labels[@]}" | ${pkgs.wofi}/bin/wofi --dmenu --hide-search --cache-file /dev/null --width 620 --lines ${toString (2 + builtins.length extraEntries)}) || exit 0
      [ -z "$sel" ] && exit 0
      for i in "''${!labels[@]}"; do
        if [ "''${labels[$i]}" = "$sel" ]; then
          exec ${pkgs.runtimeShell} -c "''${cmds[$i]}"
        fi
      done
    '';
  in {
    hm = {
      # 스크립트를 home.packages에 명시적으로 추가해 HM 클로저에 포함시킴
      # (settings.bindl 문자열 내 스토어 경로는 의존성 추적에서 누락될 수 있음)
      home.packages = lib.optionals (config.workspace.type == "laptop") [
        toggleTouchpad
        toggleTouchscreen
        inputPolicy
        restoreInput
        deviceMenu
        extkbdCli
        volumeControl
        brightnessControl
        lidScreen
        lidPolicy
      ];

      # 덮개 정책을 가장 먼저(화면 끄기가 느린 소비자 뒤로 밀리지 않게), 그다음 입력 정책
      posture.consumers = lib.mkIf (config.workspace.type == "laptop") (lib.mkMerge [
        (lib.mkBefore ["${lidPolicy}/bin/lid-policy"])
        ["${inputPolicy}/bin/hypr-input-policy"]
      ]);

      # 외부 키보드 감시: 입력 장치 추가/제거와 블루투스 연결 변화가 있을 때만(이벤트 구동, 폴링 없음) 입력 장치 정책을 다시 실행한다.
      # 내장 키보드를 지정한 노트북에서만 만든다(정책이 그 키보드만 건드리므로). Hyprland 환경 변수가 올라온 뒤(graphical-session)에 시작해야 hyprctl 이 동작한다.
      # 감시 대상(udevadm/gdbus)이 종료하면 이 서비스도 실패 종료하고 5초 뒤 다시 시작(시작 때 정책을 한 번 돌려 놓친 변화를 맞춘다). 시작 제한은 두지 않는다.
      systemd.user.services.extkbd-watch = lib.mkIf (config.workspace.type == "laptop" && kbName != null) {
        Unit = {
          Description = "외부 키보드 연결/해제 감시 (내장 키보드 끄기/켜기 정책 재실행)";
          After = ["graphical-session.target"];
          PartOf = ["graphical-session.target"];
          StartLimitIntervalSec = 0;
        };
        Service = {
          ExecStart = "${extkbdCli}/bin/extkbd watch";
          Environment = ["EXTKBD_POLICY=${inputPolicy}/bin/hypr-input-policy"];
          Restart = "on-failure";
          RestartSec = 5;
        };
        Install.WantedBy = ["graphical-session.target"];
      };

      # 입력 장치 정책을 사용 모드 허브의 소비자로 등록. 로그인(hyprland.start)/reload(config.reloaded) 때 실행하는 것도 허브가 함
      # (이유: Hyprland 는 시작/reload 때 장치를 모두 켠 상태로 되돌림)

      wayland.windowManager.hyprland.settings = {
        # == Generic Media Bindings ==
        bindel =
          [
            ", XF86AudioRaiseVolume, exec, ${volumeControl}/bin/vol-control up"
            ", XF86AudioLowerVolume, exec, ${volumeControl}/bin/vol-control down"
            ", XF86AudioMute, exec, ${volumeControl}/bin/vol-control mute"
            ", XF86AudioMicMute, exec, ${volumeControl}/bin/vol-control mic"
          ]
          ++ lib.optionals (config.workspace.type == "laptop") [
            ", XF86MonBrightnessUp, exec, ${brightnessControl}/bin/brt-control up"
            ", XF86MonBrightnessDown, exec, ${brightnessControl}/bin/brt-control down"
          ];

        # == Laptop Specific Bindings ==
        bindl = lib.mkIf (config.workspace.type == "laptop") [
          # 입력 장치 메뉴 (터치패드 키)
          # (이전에는 터치패드를 바로 토글했음. 이제는 입력 장치 메뉴를 띄우고, 터치패드 토글은 메뉴 항목으로 이동)
          "${config.wayland.windowManager.hyprland.touchpadToggleKey}, exec, ${deviceMenu}/bin/hypr-device-menu"

          # 덮개 스위치 (로그인 잠금 및 전원 관리)
          # 덮개를 닫으면 바로 잠금(허브/센서에 의존하지 않음). 화면 끄기/켜기와 전원 프로필은 허브의 소비자 lid-policy 가 맡는다
          ", switch:on:Lid Switch, exec, loginctl lock-session"
        ];
      };
    };
  });
in {
  inherit (base) imports;

  # (주의: options는 mkIf로 감쌀 수 없으므로 항상 선언)
  options.wayland.windowManager.hyprland = {
    internalKeyboardName = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "at-translated-set-2-keyboard";
      description = "내장 키보드의 Hyprland 장치 이름(`hyprctl devices` 의 keyboards). 텐트/태블릿 모드에서 정책이 이 키보드를 끈다. null 이면 키보드는 건드리지 않음.";
    };
    touchscreenUsbId = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      example = "04f3:2ffa";
      description = "터치스크린의 USB 장치 ID(`lsusb`, 벤더:제품). 지정하면 정책이 **터치스크린을 끈 동안에만** 그 USB 장치의 런타임 절전을 켜고(`power/control=auto`: 장치와 xHCI 가 잠들어 전력을 아낌), 켤 때는 먼저 깨운다(`on`). 덮개를 닫은 쉬는 상태 실측에서 약 0.5 W 차이. power/control 파일을 이 사용자가 쓸 수 있어야 한다(호스트의 udev 규칙). null 이면 건드리지 않음.";
    };
    touchpadToggleKey = lib.mkOption {
      type = lib.types.str;
      default = ", XF86TouchpadToggle";
      description = "Touchpad toggle key binding for Hyprland.";
    };
    deviceMenuExtraEntries = lib.mkOption {
      type = lib.types.listOf (lib.types.submodule {
        options = {
          label = lib.mkOption {
            type = lib.types.str;
            description = "메뉴에 표시할 이름";
          };
          command = lib.mkOption {
            type = lib.types.str;
            description = "선택 시 실행할 셸 명령";
          };
        };
      });
      default = [];
      description = "입력 장치 메뉴(hypr-device-menu)에 추가할 항목. 호스트 전용 동작(예: 특정 터치패드 드라이버 재시작)용.";
    };
    lidSwitchOnExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is closed (switch:on).";
    };
    lidSwitchOffExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is opened (switch:off).";
    };
  };
}
