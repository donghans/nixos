{
  config,
  lib,
  unstable,
  unstable-fallback,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.llm-cli;

  # (목적: Wayland 터미널(kitty, alacritty 등)에서 LLM CLI의 Home/End 키 깨짐 현상 수정)
  #
  # 원인: gemini-cli, claude-code 모두 시작 시 kitty keyboard protocol 쿼리(\x1b[?u)를 보내고,
  # kitty/alacritty 등 최신 Wayland 터미널이 이를 지원한다고 응답하면 프로토콜을 활성화(\x1b[>1u).
  # 이 모드에서 Home/End 키가 앱 자체의 키 파서가 처리하지 못하는 확장 시퀀스로 전송됨.
  # kmscon(TTY)은 해당 프로토콜을 지원하지 않아 정상 동작.

  # gemini-cli: enableKittyKeyboardProtocol() 함수 본문을 no-op으로 교체
  gemini = unstable.gemini-cli.overrideAttrs (old: {
    postInstall =
      (old.postInstall or "")
      + ''
              substituteInPlace $out/share/gemini-cli/chunk-KLFFCKY4.js \
                --replace-fail \
                'function enableKittyKeyboardProtocol() {
          writeToStdout("\x1B[>1u");
        }' \
                'function enableKittyKeyboardProtocol() {
          /* patched: kitty keyboard protocol disabled to fix Home/End on Wayland */
        }'
      '';
  });

  # claude-code: Xd6(kitty enable 시퀀스 변수)를 빈 문자열로 교체
  claude = unstable-fallback.claude-code.overrideAttrs (old: {
    postInstall =
      (old.postInstall or "")
      + ''
        substituteInPlace $out/lib/node_modules/@anthropic-ai/claude-code/cli.js \
          --replace-fail \
          'Xd6=cz(">1u")' \
          'Xd6=""'
      '';
  });
in
  {options.mods.devel.llm-cli.enable = mkEnableOption "LLM CLI tools";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) {
        home.packages = [claude gemini];
      };
    }
  )
