{mkModHere, ...}:
mkModHere __curPos "LLM CLI tools" ({unstable, ...}: let
  # (목적: Wayland 터미널(kitty, alacritty 등)에서 LLM CLI의 Home/End 키 깨짐 현상 수정)
  #
  # 원인: gemini-cli, claude-code 모두 시작 시 kitty keyboard protocol 쿼리(\x1b[?u)를 보내고,
  # kitty/alacritty 등 최신 Wayland 터미널이 이를 지원한다고 응답하면 프로토콜을 활성화(\x1b[>1u).
  # 이 모드에서 Home/End 키가 앱 자체의 키 파서가 처리하지 못하는 확장 시퀀스로 전송됨.
  # kmscon(TTY)은 해당 프로토콜을 지원하지 않아 정상 동작.
  # gemini-cli: enableKittyKeyboardProtocol() 함수 본문을 no-op으로 교체
  # chunk 파일명은 빌드마다 해시가 바뀌므로 grep으로 동적 탐색
  gemini = unstable.gemini-cli.overrideAttrs (old: {
    postInstall =
      (old.postInstall or "")
      + ''
        target=$(grep -rl 'enableKittyKeyboardProtocol' $out/share/gemini-cli/ || true)
        if [ -n "$target" ]; then
          sed -i 's/writeToStdout("\\x1B\[>1u")//g' $target
          echo "patched: kitty keyboard protocol disabled in $target"
        else
          echo "WARNING: enableKittyKeyboardProtocol not found in gemini-cli bundle, skipping patch"
        fi
      '';
  });

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
    home.packages = [claude gemini];

    # Gemini CLI 지침 (기존 메모리 동기화 및 전역 원칙 강제)
    home.file.".gemini/GEMINI.md" = {
      text = ''
        # Gemini Added Memories
        - Answer in korean.
        - 코드 수정은 최소한으로, git diff 확인을 통해 잘못 수정된것은 정정할 것
        - md 등의 문서가 길어진다면 분리해서 작성할 것
      '';
      force = true; # 기존 파일이 있더라도 Nix 관리 하에 둠
    };
  };
})
