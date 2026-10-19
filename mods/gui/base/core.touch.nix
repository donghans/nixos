# 터치스크린 제스처(hyprgrass 플러그인) — Hyprland 자체의 터치 제스처는 워크스페이스 스와이프 하나뿐이고 `Super`+드래그(bindm)는 터치에 적용되지 않아서,
# 터치로 창을 옮기고 크기를 조절하고 워크스페이스를 넘기려면 플러그인이 필요하다. (조사/시험 기록: _docs/content/explanation/posture.md)
#
# 버전 선택(2026-10-19, 중첩 Hyprland 로 시험): Hyprland 는 stable(0.55.2)을 유지하고 hyprgrass 는 **Lua 지원 커밋 d094a3e6**(업스트림 hyprpm 이 0.55.1/0.55.4 에 고정)을 쓴다.
#  - 0.55.2 에 고정된 3236fbb1 은 Hyprlang 시절 코드(getConfigValue 16곳)라 Lua 설정에서 SEGV → 쓰면 안 됨(바로 다음 날 커밋 d094a3e6 부터 Lua 방식).
#  - d094a3e6 은 0.55.2 헤더로 빌드되고, 중첩 Hyprland(0.55.2)에서 로드/Lua 설정(hl.config, hyprgrass.bind/gesture)이 오류 없이 받아들여졌다. **실제 터치 동작은 중첩 환경에서 못 시험함**.
#  - unstable(Hyprland 0.56.2)은 세 변종 모두 그대로는 빌드가 안 된다: nixpkgs 패키지(d094a3e6)는 API 변경으로, 0.56.2 고정 커밋(8e605468)은 wf-touch 불일치로, 최신(6adcebc2)은 LOG 매크로 미선언으로 실패.
# wf-touch 는 nixpkgs 에서 테스트(doctest) 링크 때문에 빌드가 실패해서 테스트를 끈다.
#
# 플러그인이 비정상 종료하면 Hyprland 도 같이 종료된다(pcall 은 Lua 오류만 막음). 플러그인 로드 실패(Lua 오류)는 pcall 로 막아 설정 전체는 안 깨진다.
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  config,
  ...
}: let
  convertible = config.workspace.convertible; # 2-in-1 호스트만(host.toml `convertible = true`)
  # 켬(2026-10-19, 사용자 승인): 빌드/로드/Lua 설정 수락은 중첩 Hyprland 로 확인했지만 **실제 터치 이벤트 처리는 이 세션에서 처음 시험**한다
  # (중첩 Hyprland 는 바깥 창의 터치를 받지 못해 터치 시험이 불가능: aquamarine 의 Wayland 백엔드는 키보드/포인터만 구현).
  # 터치스크린이 꺼져 있으면(노트북 모드의 마지막 수동 상태) 제스처도 안 들어온다 — 텐트/태블릿에서는 강제로 켜지고, 노트북 모드에서는 입력 장치 메뉴로 켠다.
  # **로그인 때마다 Hyprland 가 죽으면**(이 플러그인이 원인일 때) tty 에서 이 줄을 false 로 되돌리고 `nixup home`:
  #   cd ~/nixos && sed -i 's/enableHyprgrass = true;/enableHyprgrass = false;/' mods/gui/base/core.touch.nix && nixup home
  enableHyprgrass = true;
  wf-touch = pkgs.wf-touch.overrideAttrs (old: {
    mesonFlags = (old.mesonFlags or []) ++ ["-Dtests=disabled"];
  });
  hyprgrass = pkgs.hyprlandPlugins.hyprgrass.overrideAttrs (old: {
    version = "0.8.2-d094a3e-lua";
    src = pkgs.fetchFromGitHub {
      owner = "horriblename";
      repo = "hyprgrass";
      rev = "d094a3e62f6ecaeb41515982d3e13edefaf8a4e7";
      hash = "sha256-tCt7FNc1RBHou/ym7B0XzoOqqNq8Df+dizEDkAgJ4U0=";
    };
    buildInputs = map (x:
      if (x.pname or "") == "wf-touch"
      then wf-touch
      else x)
    old.buildInputs;
  });
in {
  hm = lib.mkIf (convertible && enableHyprgrass) {
    wayland.windowManager.hyprland.extraConfig = ''
      -- 터치 제스처(hyprgrass). 플러그인 로드가 실패해도 나머지 설정은 그대로 진행
      do
        local ok, err = pcall(function() hl.plugin.load("${hyprgrass}/lib/libhyprgrass.so") end)
        if ok and hl.plugin and hl.plugin.hyprgrass then
          pcall(function()
            hl.config({
              plugin = {
                hyprgrass = {
                  sensitivity = 4.0,            -- 태블릿 화면에서는 기본값(1.0)이 둔함(권장값)
                  long_press_delay = 400,       -- ms
                  resize_on_border_long_press = true,   -- 창 테두리/틈새를 길게 누른 채 끌면 크기 조절
                  edge_margin = 10,
                },
              },
            })
            -- 손가락 3개: 길게 누른 뒤 끌면 창 이동(Super+드래그의 터치 버전)
            hl.plugin.hyprgrass.bind({
              pattern = { kind = "longpress", fingers = 3 },
              action = hl.dsp.window.drag(),
              mouse = true,
            })
            -- 손가락 3개 좌우 스와이프: 워크스페이스 전환
            hl.plugin.hyprgrass.gesture({
              pattern = { kind = "swipe", fingers = 3, direction = "horizontal" },
              action = "workspace",
            })
          end)
        else
          hl.exec_cmd("notify-send -u low 'hyprgrass' '터치 제스처 플러그인을 불러오지 못했습니다'")
        end
      end
    '';
  };
})
