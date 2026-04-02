{ pkgs, ... }: let
  yarn-pnpm-wrapper = pkgs.writeShellScriptBin "yarn" ''
    # 1. yarn.lock이 있는 프로젝트인지 확인
    if [ -f "yarn.lock" ]; then

      # .git 디렉토리가 있는 경우에만 exclude 처리
      if [ -d ".git" ]; then
        EXCLUDE_FILE=".git/info/exclude"
        mkdir -p "$(dirname "$EXCLUDE_FILE")"

        # pnpm 관련 파일을 .git/info/exclude에 조용히 추가
        for item in "pnpm-lock.yaml" "node_modules"; do
          if ! grep -q "$item" "$EXCLUDE_FILE" 2>/dev/null; then
            echo "$item" >> "$EXCLUDE_FILE"
          fi
        done
      fi

      # 2. pnpm-lock.yaml이 없으면 import 수행
      if [ ! -f "pnpm-lock.yaml" ]; then
        echo "💡 [pnpm-wrapper] yarn.lock 감지: pnpm-lock.yaml을 생성합니다..."
        ${pkgs.pnpm}/bin/pnpm import
      fi

      # 3. 모든 명령어를 pnpm으로 대리 실행
      echo "🚀 [pnpm-wrapper] pnpm을 통해 명령어를 실행합니다: $@"
      exec ${pkgs.pnpm}/bin/pnpm "$@"
    else
      # 4. yarn.lock이 없는 일반 프로젝트라면?
      # 시스템에 설치된 진짜 yarn이 있다면 거기로 보내거나, pnpm을 기본으로 쓰게 합니다.
      # 여기서는 pnpm을 메인으로 쓰기로 하셨으니 pnpm으로 보냅니다.
      exec ${pkgs.pnpm}/bin/pnpm "$@"
    fi
  '';
in {
  home.packages = [ yarn-pnpm-wrapper ];
}
