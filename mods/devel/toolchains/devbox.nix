{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Devbox global profile" ({
  config,
  pkgs,
  ...
}: let
  # (목적: 템플릿 복사 및 초기화를 한 번에 수행하는 통합 헬퍼)
  devbox-setup = pkgs.writeShellScriptBin "devbox-setup" ''
    TYPE="''${1:-}"
    if [ -z "$TYPE" ]; then
      echo "Usage: devbox-setup [node|flutter]"
      exit 1
    fi

    TEMPLATE_DIR="${config.home.homeDirectory}/${builtins.baseNameOf config.workspace.nixosRepo}/mods/_data/devbox"
    TARGET_TEMPLATE="$TEMPLATE_DIR/$TYPE.json"

    if [ ! -f "$TARGET_TEMPLATE" ]; then
      echo "❌ Error: Template '$TYPE' not found at $TARGET_TEMPLATE"
      exit 1
    fi

    cp "$TARGET_TEMPLATE" ./devbox.json
    echo "✅ Copied $TYPE template to ./devbox.json"

    # devbox.json에 내장된 setup-all 실행 (direnv, stealth 등 자동화)
    devbox run setup-all
  '';
in {
  hm = {
    home.packages = [
      pkgs.devbox
      devbox-setup
    ];
  };
})
