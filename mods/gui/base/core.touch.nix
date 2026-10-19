# 터치스크린 제스처(hyprgrass 플러그인) — Hyprland 자체의 터치 제스처는 워크스페이스 스와이프 하나뿐이고 `Super`+드래그(bindm)는 터치에 적용되지 않아서,
# 터치로 창을 옮기고 크기를 조절하고 워크스페이스를 넘기려면 플러그인이 필요하다. (조사/시험 기록: _docs/content/explanation/posture.md)
#
# 버전 주의: Hyprland 플러그인은 헤더 버전이 맞아야 한다. nixpkgs 의 hyprgrass(2025-10)는 Hyprland 0.55 와 컴파일이 안 되고,
# 업스트림 hyprpm.toml 이 "Hyprland v0.55.2(39d7e209) ↔ hyprgrass 3236fbb1" 로 고정해 둔 커밋을 쓴다. Hyprland 를 올리면 이 rev 도 같이 올려야 한다.
# wf-touch 는 nixpkgs 에서 테스트(doctest) 링크 때문에 빌드가 실패해서 테스트를 끈다.
#
# 플러그인이 없거나 로드에 실패해도 Hyprland 설정 전체가 깨지지 않도록 pcall 로 감싼다(제스처만 안 됨). 단, 플러그인 자체가 비정상 종료하면 Hyprland 도 같이 종료된다.
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  config,
  ...
}: let
  isLaptop = config.workspace.type == "laptop";
  # 비활성(2026-10-19 원인 확정): 이 고정 커밋(3236fbb1)은 Hyprlang 시절 코드라 getConfigValue("plugin:touch_gestures:*")를 15곳 넘게 쓰는데,
  # Lua 설정(Hyprland 0.55)에서는 그 값들이 등록되지 않아 nullptr 을 바로 역참조한다 → pluginInit(main.cpp:380)과 GestureManager 생성자(GestureManager.cpp:83)에서 SEGV.
  # 중첩 Hyprland 로 두 번 재현했고, 첫 줄만 널 검사로 막아도 다음 지점에서 죽는다(패치로 해결 불가). 업스트림 최신판(2026-10-18)은 Hyprlang 호환층을 지운 Lua 네이티브라서
  # Hyprland 0.56.x 용이다 → 쓰려면 Hyprland 를 올려야 함. 조사 기록: _docs/content/explanation/posture.md. 켜기 전에 반드시 중첩 Hyprland 로 먼저 로드해 볼 것.
  enableHyprgrass = false;
  wf-touch = pkgs.wf-touch.overrideAttrs (old: {
    mesonFlags = (old.mesonFlags or []) ++ ["-Dtests=disabled"];
  });
  hyprgrass = pkgs.hyprlandPlugins.hyprgrass.overrideAttrs (old: {
    version = "0.8.2-hl0.55.2";
    src = pkgs.fetchFromGitHub {
      owner = "horriblename";
      repo = "hyprgrass";
      rev = "3236fbb1a2f9c3a91ac1a4f390ed6d510c2aaf19";
      hash = "sha256-4mXQwdPuWNDAwVJF+SbifB33K1eDpQYpXKT06hNmnVU=";
    };
    buildInputs = map (x:
      if (x.pname or "") == "wf-touch"
      then wf-touch
      else x)
    old.buildInputs;
  });
in {
  hm = lib.mkIf (isLaptop && enableHyprgrass) {
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
