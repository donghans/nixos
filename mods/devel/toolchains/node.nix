{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Node.js toolchain" ({
  config,
  pkgs,
  ...
}: {
  hm = {
    home.packages = with pkgs; [
      node-wrapped
      pnpm-wrapped
      pnpm-yarn-wrapper
      pnpm-npm-wrapper
    ];

    xdg.configFile."pnpm/rc".text = ''
      # store — btrfs CoW 유지
      store-dir=/home/${config.workspace.username}/.local/share/pnpm/store
      package-import-method=clone

      # npm-compatible flat node_modules (no .pnpm/, no symlinks)
      node-linker=hoisted

      # workspace: 없이도 로컬 패키지 우선 링크 (npm 동작)
      link-workspace-packages=true

      # peer deps — npm v7+ 동작
      auto-install-peers=true
      strict-peer-dependencies=false

      # npm alias(pnpm)가 packageManager 필드를 보고 거부하지 않도록
      package-manager-strict=false

      # build script 허용 여부를 물어보는 pnpm-workspace.yaml 자동 생성 방지
      dangerously-allow-all-builds=true
    '';

    home.sessionVariables = {
      # pnpm 공식 env var — 스크립트/CI에서 rc 없이도 스토어 경로 인식
      PNPM_STORE_DIR = "/home/${config.workspace.username}/.local/share/pnpm/store";
    };

    home.shellAliases = {
      npx = "pnpm dlx";
    };
  };
})
