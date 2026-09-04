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

  # (목적: Node 환경에 Prisma 탐색 및 LD_LIBRARY_PATH 주입)
  wrapNode = pkg: binName: (prev.mkWrapper {
    inherit pkg binName;
    libs = with prev; [stdenv.cc.cc openssl];
    bins = with prev; [openssl findutils];
    run = prismaDetectionScript;
  });

  # (목적: 프로젝트 node_modules 경로를 registry에 추적하고 duperemove로 Btrfs block dedup)
  npmNodeDedup = prev.writeShellScriptBin "npm-node-dedup" ''
    set -euo pipefail
    REGISTRY_DIR="''${XDG_DATA_HOME:-''$HOME/.local/share}/npm-node-dedup"
    REGISTRY="''$REGISTRY_DIR/registry"
    HASH_DIR="''${XDG_CACHE_HOME:-''$HOME/.cache}/npm-node-dedup"
    HASHFILE="''$HASH_DIR/dedup.db"
    mkdir -p "''$REGISTRY_DIR" "''$HASH_DIR"

    PROJ_DIR="''${INIT_CWD:-''$PWD}"
    PROJ_NM="''$PROJ_DIR/node_modules"
    if [ -f "''$PROJ_DIR/package.json" ] && [ -d "''$PROJ_NM" ]; then
      grep -qxF "''$PROJ_NM" "''$REGISTRY" 2>/dev/null || echo "''$PROJ_NM" >> "''$REGISTRY"
    fi

    [ -f "''$REGISTRY" ] || exit 0
    VALID=()
    while IFS= read -r nm; do
      [ -z "''$nm" ] && continue
      proj=$(dirname "''$nm")
      if [ -d "''$nm" ] && [ -f "''$proj/package.json" ]; then
        VALID+=("''$nm")
      fi
    done < "''$REGISTRY"
    printf '%s\n' "''${VALID[@]}" > "''$REGISTRY"

    [ "''${#VALID[@]}" -ge 2 ] || exit 0
    duperemove -r -d --hashfile="''$HASHFILE" "''${VALID[@]}" 2>/dev/null || true
  '';

  # (목적: 순정 npm pass-through + install 시 prefer-dedupe 인라인 주입 + prune + dedup)
  npmWrapper = prev.lib.hiPrio (prev.writeShellScriptBin "npm" ''
    REAL_NPM="${prev.nodejs_24}/bin/npm"
    CMD="''${1:-}"

    case "''$CMD" in
      install|i)
        shift
        "''$REAL_NPM" install --prefer-dedupe "$@"
        EXIT=$?
        [ "''$EXIT" -eq 0 ] && "''$REAL_NPM" prune 2>/dev/null || true
        [ "''$EXIT" -eq 0 ] && npm-node-dedup 2>/dev/null || true
        exit "''$EXIT"
        ;;
      ci)
        "''$REAL_NPM" "$@"
        EXIT=$?
        [ "''$EXIT" -eq 0 ] && npm-node-dedup 2>/dev/null || true
        exit "''$EXIT"
        ;;
      *)
        exec "''$REAL_NPM" "$@"
        ;;
    esac
  '');
in {
  node-wrapped = wrapNode prev.nodejs_24 "node";
  npm-wrapper = npmWrapper;
  npm-node-dedup = npmNodeDedup;
}
