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
  };
})
