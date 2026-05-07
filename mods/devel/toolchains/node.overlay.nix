# Node.js & Tooling Overlay
_final: prev: let
  # == Prisma & Node Wrapper Logic ==
  # Prisma 엔진을 현재 디렉토리에서 상위로 올라가며 찾는 쉘 스크립트
  # (참고: Nix ''...'' 문자열에서 ''$ 는 쉘 변수 $ 의 이스케이프 → 출력 시 $VAR 로 확장)
  prismaDetectionScript = ''
    curr="''$PWD"
    while [ "''$curr" != "/" ]; do
      engines_dir="''$curr/node_modules/@prisma/engines"
      if [ -d "''$engines_dir" ]; then
        export PRISMA_ENGINES_DIR="''$engines_dir"
        _lib=$(find "''$engines_dir" -name "libquery_engine-*.so.node" | head -n 1)
        [ -n "''$_lib" ] && export PRISMA_QUERY_ENGINE_LIBRARY="''$_lib"
        _bin=$(find "''$engines_dir" -maxdepth 1 -name "query-engine-*" ! -name "*.so*" ! -name "*.node" | head -n 1)
        [ -n "''$_bin" ] && export PRISMA_QUERY_ENGINE_BINARY="''$_bin"
        _schema=$(find "''$engines_dir" -maxdepth 1 -name "schema-engine-*" ! -name "*.so*" ! -name "*.node" | head -n 1)
        [ -n "''$_schema" ] && export PRISMA_SCHEMA_ENGINE_BINARY="''$_schema"
        break
      fi
      curr=$(dirname "''$curr")
    done
    unset _lib _bin _schema
  '';

  # (목적: Node 환경에 Prisma 탐색 및 PNPM 글로벌 최적화 변수 주입)
  wrapNode = pkg: binName: (prev.mkWrapper {
    inherit pkg binName;
    libs = with prev; [stdenv.cc.cc openssl];
    bins = with prev; [openssl findutils];
    run = prismaDetectionScript;
  });

  # (목적: yarn 명령어를 pnpm으로 대리 실행하는 호환성 래퍼)
  yarnPnpmWrapper = prev.writeShellScriptBin "yarn" ''
    if [ -f "yarn.lock" ]; then
      if [ -d ".git" ]; then
        EXCLUDE_FILE=".git/info/exclude"
        mkdir -p "$(dirname "$EXCLUDE_FILE")"
        for item in "pnpm-lock.yaml" "node_modules"; do
          if ! grep -q "$item" "$EXCLUDE_FILE" 2>/dev/null; then
            echo "$item" >> "$EXCLUDE_FILE"
          fi
        done
      fi

      if [ ! -f "pnpm-lock.yaml" ]; then
        echo "💡 [pnpm-wrapper] yarn.lock 감지: pnpm-lock.yaml을 생성합니다..."
        pnpm import
      fi

      echo "🚀 [pnpm-wrapper] pnpm을 통해 명령어를 실행합니다: $@"
      exec pnpm "$@"
    else
      exec pnpm "$@"
    fi
  '';
in {
  node-wrapped = wrapNode prev.nodejs_24 "node";
  pnpm-wrapped = wrapNode prev.pnpm "pnpm";
  pnpm-yarn-wrapper = yarnPnpmWrapper;
}
