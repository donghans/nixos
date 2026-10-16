{mkMod, ...}:
mkMod __curPos "Lazygit (터미널 git UI) + delta" ({pkgs, ...}: {
  hm = {
    # delta: lazygit 이 diff 를 직접 그리는 대신 넘겨주는 보기 좋은 pager (단어 단위 변경 강조, 문법 색).
    # ~/.gitconfig 는 건드리지 않고 lazygit 의 pager 설정으로만 연결
    home.packages = [pkgs.delta];

    programs.lazygit = {
      enable = true;
      settings = {
        gui = {
          # Hyprland 활성 창 테두리(core.ui.nix) 및 wofi/clipui 와 같은 색
          theme = {
            activeBorderColor = ["#33ccff" "bold"];
            inactiveBorderColor = ["#595959"];
            selectedLineBgColor = ["#268bd2"];
            selectedRangeBgColor = ["#268bd2"];
          };
          # (Nerd Font 가 아니라 아이콘을 끔)
          nerdFontsVersion = "";
          showFileIcons = false;
          # 창 크기에 따라 패널 배치가 바뀌는 반응형 (htop 처럼)
          sidePanelWidth = 0.33;
          expandFocusedSidePanel = true;
        };
        git = {
          # (lazygit 0.61 부터 paging 객체가 pagers 배열로 바뀜 — 옛 형식이면 설정 자동 이전을 시도하다
          #  Home Manager 의 읽기 전용 설정 파일에 쓰지 못하고 종료함)
          pagers = [
            {
              colorArg = "always";
              pager = "delta --dark --paging=never --line-numbers";
            }
          ];
        };
        # 첫 실행 환영 팝업 / 업데이트 안내 끄기
        disableStartupPopups = true;
        promptToReturnFromSubprocess = false;
        notARepository = "skip";
      };
    };

    home.shellAliases.lg = "lazygit";
  };
})
