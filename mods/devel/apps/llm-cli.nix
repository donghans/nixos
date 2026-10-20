{
  mkModOf,
  unstable,
  ...
}:
mkModOf "mods.devel" __curPos "LLM CLI tools" ({
  pkgs,
  unstable,
  config,
  lib,
  ...
}: let
  # 노트북에서는 Claude Code TUI 의 애니메이션(스피너 등)을 줄여서 켠다(`--settings` 로 한 키만 덧씌움; 사용자 settings.json 은 Claude 가 직접 쓰는 가변 파일이라 건드리지 않음).
  # 목적: (1) **측정 위생** — 이 저장소의 목적은 Wayland 세션 사용 시 배터리 최적화이고 Claude 를 VT2(kmscon)에 두는 것도 그 측정에 변수를 섞지 않으려는 것인데,
  # VT2 가 활성일 때 TUI 가 화면을 갱신하면 약 +1.3 W 가 섞인다(2026-10-20 측정, power-evidence.md #34). (2) 화면 갱신이 줄면 PSR 등 모니터 출력 최적화가 더 잘 걸리므로
  # 모션 감소는 효과 측정 결과와 무관하게 유지한다(사용자 결정). `CLAUDE_MOTION=normal claude` 로 끌 수 있다.
  reduceMotion = config.workspace.type == "laptop";
  reduceMotionSnippet = lib.optionalString reduceMotion ''
    if [ "''${CLAUDE_MOTION:-reduced}" != normal ]; then
      set -- --settings '{"prefersReducedMotion":true}' "$@"
    fi
  '';
  # (목적: Wayland 터미널(kitty, alacritty 등)에서 LLM CLI의 Home/End 키 깨짐 현상 수정)
  #
  # (claude-code 쪽 패치는 제거함: 4월에 패키지가 네이티브 바이너리 배포로 바뀌면서 패치 대상 cli.js 가 사라져
  #  "pattern not found, skipping" 으로 아무 효과가 없었고, 현재 버전에서는 Home/End 문제도 재현되지 않음)
  # 원인: gemini-cli, claude-code 모두 시작 시 kitty keyboard protocol 쿼리(\x1b[?u)를 보내고,
  # kitty/alacritty 등 최신 Wayland 터미널이 이를 지원한다고 응답하면 프로토콜을 활성화(\x1b[>1u).
  # 이 모드에서 Home/End 키가 앱 자체의 키 파서가 처리하지 못하는 확장 시퀀스로 전송됨.
  # kmscon(TTY)은 해당 프로토콜을 지원하지 않아 정상 동작.
  # gemini-cli: enableKittyKeyboardProtocol() 함수 본문을 no-op으로 교체
  # chunk 파일명은 빌드마다 해시가 바뀌므로 grep으로 동적 탐색
  # gemini = unstable.gemini-cli.overrideAttrs (old: {
  #   postInstall =
  #     (old.postInstall or "")
  #     + ''
  #       target=$(grep -rl 'enableKittyKeyboardProtocol' $out/share/gemini-cli/ || true)
  #       if [ -n "$target" ]; then
  #         sed -i 's/writeToStdout("\\x1B\[>1u")//g' $target
  #         echo "patched: kitty keyboard protocol disabled in $target"
  #       else
  #         echo "WARNING: enableKittyKeyboardProtocol not found in gemini-cli bundle, skipping patch"
  #       fi
  #     '';
  # });
  #
  # (목적: claude 래퍼가 노출하는 LD_LIBRARY_PATH 의 alsa-lib 가 다른 프로그램을 깨뜨리는 문제 수정)
  # nixpkgs claude-code 는 /voice(음성 입력) 네이티브 모듈이 libasound 를 dlopen 하도록 래퍼에
  # `--prefix LD_LIBRARY_PATH : alsa-lib` 를 붙임(nixpkgs PR #518983). unstable 의 alsa-lib 는 더 새 glibc(2.44)로
  # 빌드돼 있어, 이 변수를 물려받는 glibc 2.42 프로그램(ONLYOFFICE 등)이 `GLIBC_2.43 not found` 로 죽음.
  # → alsa-lib 만 stable 것으로 교체. 새 glibc 는 옛 glibc 로 빌드된 라이브러리를 그대로 로드할 수 있어 양쪽 모두 안전함
  #   (claude 바이너리는 libc/libm/libpthread/librt 를 미리 로드하고 stable libasound 의 의존도 같은 목록).
  claude = unstable.claude-code.override {inherit (pkgs) alsa-lib;};
in {
  hm = {
    home.packages = [claude unstable.antigravity-cli];

    # Gemini CLI 지침 (기존 메모리 동기화 및 전역 원칙 강제)
    # home.file.".gemini/GEMINI.md" = {
    #   text = ''
    #     # Gemini Added Memories
    #     - Answer in korean.
    #     - 코드 수정은 최소한으로, git diff 확인을 통해 잘못 수정된것은 정정할 것
    #     - md 등의 문서가 길어진다면 분리해서 작성할 것
    #   '';
    #   force = true; # 기존 파일이 있더라도 Nix 관리 하에 둠
    # };

    # Claude Code 전역 지침
    # 소스가 nix에 있으므로 git으로 diff 추적이 되고, 생성물은 store로 심볼릭링크되어 읽기 전용.
    # -> ~/.claude/CLAUDE.md 를 직접 수정하지 말고 이 블록을 수정할 것.
    home.file.".claude/CLAUDE.md" = {
      text = ''
        # 환경 정보
        - 이 시스템은 NixOS이며, 스왑 영역의 일부는 ZRAM으로 구성되어 있을 수 있습니다.
          메모리/스왑 관련 작업(OOM 대응, 스왑 크기 조정 등) 전에 실제 스왑이 디스크인지 ZRAM인지 먼저 확인하세요.
        - 하드웨어/OS 상세 스펙(디스크, 파일시스템, 부트로더, 커널 파라미터 등)은 추측하지 말고
          `~/nixos/hosts/(현재 호스트명).nix`, `~/nixos/hosts/(현재 호스트명).toml`, 있다면 `~/nixos/hosts/(현재 호스트명)/` 디렉토리를 직접 읽어 확인하세요.
          현재 호스트명은 `hostname` 명령으로 확인합니다.
        - 이 프레임워크(`nixup`, mods/hosts 구조 등)에 대한 전반적인 설명은 `~/nixos/README.md`를 먼저 읽어보세요.
        - 명령어 실행 중 시스템에 없는 패키지가 필요하다면, 임의로 설치하지 말고 `nix shell nixpkgs#<패키지명>`으로 일회성 실행하세요.
        - 이 시스템에는 `unzip`이 없습니다. zip 등의 압축 해제는 `7z x <파일> -o<대상디렉토리>`를 사용하세요
          (`unzip`을 위해 `nix shell nixpkgs#unzip`을 쓰지 마세요).
        - playwright/puppeteer 등 브라우저 자동화·E2E 테스트는 호스트에서 설치·실행하지 말고 Docker 컨테이너 안에서 실행하세요
          (예: `mcr.microsoft.com/playwright` 이미지). 호스트에는 브라우저 바이너리를 받지 않도록
          `PUPPETEER_SKIP_DOWNLOAD`/`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`가 설정되어 있으니 해제하지 마세요.

        # 기록 원칙
        - 진행한 작업, 원인 파악 결과, 삽질 기록 등 project/domain 성격의 정보는
          Claude Code의 자동 메모리 시스템(`~/.claude/projects/.../memory/`)에 남기지 마세요.
          대신 작업 중인 프로젝트 저장소 내 git 추적 가능한 문서(`_docs/`, README 등)로 남기세요.
      '';
      force = true; # 기존 파일이 있더라도 Nix 관리 하에 둠 (읽기 전용 심볼릭링크)
    };

    # claude 실행 전 sudo 인증을 미리 받아두고, 백그라운드에서 60초마다 타임스탬프를 갱신.
    # (목적: 세션 도중 Claude가 sudo 필요한 명령을 실행할 때마다 비밀번호/지문 프롬프트로 막히는 것 방지)
    # -> sudoers를 NOPASSWD로 여는 대신, 최초 1회 인증 후 셸이 살아있는 동안만 캐시를 유지하는 방식.
    programs.zsh.initContent = ''
      claude() {
        sudo -v || return 1
        ( while sudo -n true 2>/dev/null; do sleep 60; kill -0 "$$" 2>/dev/null || exit; done & ) 2>/dev/null
        ${reduceMotionSnippet}
        command claude "$@"
      }
    '';
  };
})
