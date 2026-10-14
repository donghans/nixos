{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Node.js toolchain" ({
  pkgs,
  ...
}: {
  hm = {
    home.packages = with pkgs; [
      node-wrapped    # Prisma 탐색 + LD_LIBRARY_PATH
      npm-wrapper     # 순정 npm pass-through (prefer-dedupe + prune + dedup hook)
      npm-node-dedup  # Btrfs block dedup 추적 스크립트
      duperemove      # Btrfs extent-same dedup (node_modules 간 블록 공유)
    ];

    # (목적: 호스트에서 npm install 시 playwright/puppeteer 브라우저 바이너리 다운로드 차단)
    # (이유: 브라우저 테스트는 Docker(mcr.microsoft.com/playwright 등) 내에서만 실행한다.
    #        호스트(NixOS)는 동적 링킹 문제로 변수가 많고, unzip 부재로 postinstall도 실패한다.)
    # (참고: Docker 빌드 내부에는 이 환경변수가 전달되지 않으므로 컨테이너 안 설치에는 영향 없음)
    home.sessionVariables = {
      PUPPETEER_SKIP_DOWNLOAD = "true";
      PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD = "1";
    };
  };
})
