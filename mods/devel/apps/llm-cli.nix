{
  mkModOf,
  unstable,
  ...
}:
mkModOf "mods.devel" __curPos "LLM CLI tools" ({unstable, ...}: let
  # (목적: Wayland 터미널(kitty, alacritty 등)에서 LLM CLI의 Home/End 키 깨짐 현상 수정)
  #
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
  # claude-code: kitty keyboard protocol enable 시퀀스를 빈 문자열로 교체
  # ">1u"는 CSI > 1 u (kitty keyboard protocol enable) 페이로드.
  # 변수명(Xd6, yo6 등)·함수명(cz, NA 등)은 빌드마다 바뀌므로 grep으로 동적 탐색.
  claude = unstable.claude-code.overrideAttrs (old: {
    postInstall =
      (old.postInstall or "")
      + ''
        target="$out/lib/node_modules/@anthropic-ai/claude-code/cli.js"
        if grep -q '">1u"' "$target" 2>/dev/null; then
          sed -i 's/\([A-Za-z0-9_$]\{1,8\}\)=\([A-Za-z0-9_$]\{1,8\}\)(">1u")/\1=""/g' "$target"
          echo "patched: kitty keyboard protocol disabled in claude-code"
        else
          echo "WARNING: kitty keyboard protocol pattern not found in claude-code, skipping patch"
        fi
      '';
  });
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
        command claude "$@"
      }
    '';
  };
})
