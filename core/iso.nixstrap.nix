{
  pkgs,
  lib,
  metaConfig,
  ...
}: let
  # 1. lib 파일들을 Nix store에 바이트 복사 (문자열 인터폴레이션 없음 → 비 ASCII 안전)
  nixstrap-libs = pkgs.runCommand "nixstrap-libs" {} ''
    mkdir -p $out
    cp ${./scripts/nixstrap.lib-ui.sh}       $out/nixstrap.lib-ui.sh
    cp ${./scripts/nixstrap.task-input.sh}   $out/nixstrap.task-input.sh
    cp ${./scripts/nixstrap.task-disk.sh}    $out/nixstrap.task-disk.sh
    cp ${./scripts/nixstrap.task-install.sh} $out/nixstrap.task-install.sh
    cp ${./scripts/nixstrap.lib-repo.py}     $out/nixstrap.lib-repo.py
    cp ${./scripts/nixstrap.lib-part.py}     $out/nixstrap.lib-part.py
  '';

  # 2. nixstrap.sh를 ISO 시스템의 bin 폴더에 넣기 위한 '패키지' 생성
  #
  # nixstrap.sh shebang의 -p 목록을 파싱하여 runtimeInputs로 자동 주입.
  # → 도구 목록을 shebang 한 곳에서만 관리하고 여기서 중복 선언하지 않음.
  #
  # runtimeInputs의 두 가지 역할:
  #   (1) 실행 시 PATH 주입 — nixstrap이 nix-shell 없이도 python3·parted 등을 바로 사용
  #   (2) ISO 클로저 포함 — 오프라인 설치 환경에서도 해당 패키지가 /nix/store에 존재
  #
  # binary 이름을 nixstrap-wrapped로 분리하여 alias → binary 흐름을 명확히 함.
  # (alias nixstrap → sudo -E nixstrap-wrapped)
  _nixstrapPkgLine = builtins.elemAt (lib.splitString "\n" (builtins.readFile ./scripts/nixstrap.sh)) 1;
  # "#! nix-shell -i bash -p python3 git jq parted btrfs-progs util-linux"
  _nixstrapPkgStr = lib.removePrefix "#! nix-shell -i bash -p " _nixstrapPkgLine;
  nixstrapRuntimePkgs = map (name: pkgs.${name})
    (lib.filter (s: s != "") (lib.splitString " " _nixstrapPkgStr));

  nixstrap-wrapped = pkgs.writeShellApplication {
    name = "nixstrap-wrapped";

    runtimeInputs = nixstrapRuntimePkgs;

    # SCRIPT_DIR: nixstrap-libs store 경로로 주입 (lib 파일 탐색용)
    # NIXOS_REPO: ISO 빌드 시점의 레포 주소를 기본값으로 내장
    #   → alias는 sudo 권한 상승만 담당, 레포 설정은 binary 안에 캡슐화
    #   → 사용자가 Enter만 눌러도 올바른 레포가 선택됨 (변경도 가능)
    text =
      ''
        export SCRIPT_DIR="${nixstrap-libs}"
        export NIXOS_REPO="${metaConfig.nixosRepo}"
      ''
      + builtins.readFile ./scripts/nixstrap.sh;

    # 비 ASCII(한국어 주석 등) 대응을 위해 UTF-8 로케일 지정
    checkPhase = ''
      runHook preCheck
      export LC_ALL=C.UTF-8
      ${pkgs.stdenv.shellDryRun} "$target"
      ${pkgs.shellcheck}/bin/shellcheck -e SC1091,SC2034 "$target"
      runHook postCheck
    '';
  };
in {
  # nixstrap 안내 메시지 (kitty 터미널: 한국어, 그 외: 영어)
  programs.zsh.interactiveShellInit = lib.mkAfter ''
    if [[ $(tty) == /dev/tty1 || $(tty) == /dev/pts/* ]]; then
      if [[ "$TERM" == "xterm-kitty" ]]; then
        echo "--------------------------------------------------"
        echo "🚀 NixOS 커스텀 인스톨러 (Hyprland 환경)"
        echo "--------------------------------------------------"
        echo "설치를 시작하려면 아래 명령어를 입력하세요:"
        echo ""
        echo "  nixstrap"
        echo ""
        echo "저장소·호스트·파티션 선택을 대화형으로 안내합니다."
        echo "레포에 없는 호스트명을 지정하면 프리셋(workstation/server)을"
        echo "물어보고 host.toml / configuration.nix / home.nix를 자동 생성합니다."
        echo "실패 시 이전 설정을 자동 저장하여 재시도할 수 있습니다."
        echo "--------------------------------------------------"
      else
        echo "--------------------------------------------------"
        echo "🚀 NixOS Custom Installer (Hyprland)"
        echo "--------------------------------------------------"
        echo "To start the installation, enter the command below:"
        echo ""
        echo "  nixstrap"
        echo ""
        echo "Interactively guides you through repo, host, and partition selection."
        echo "If a new hostname is given, a preset (workstation/server) will be"
        echo "prompted and host.toml / configuration.nix / home.nix auto-created."
        echo "On failure, your settings are saved and can be reloaded on retry."
        echo "--------------------------------------------------"
      fi
    fi
  '';

  environment.systemPackages = [ nixstrap-wrapped ];

  environment.shellAliases = {
    nixstrap = "sudo -E nixstrap-wrapped";
  };
}
