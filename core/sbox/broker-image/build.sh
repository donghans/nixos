#!/usr/bin/env bash
# broker 최소 NixOS ct 이미지를 만든다(rootfs 와 incus 메타데이터). 결과 경로 두 개를 출력한다.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/result}
mkdir -p "$out"
nix-build '<nixpkgs/nixos>' -A config.system.build.tarball -I "nixos-config=$here/configuration.nix" -o "$out/rootfs"
nix-build '<nixpkgs/nixos>' -A config.system.build.metadata -I "nixos-config=$here/configuration.nix" -o "$out/metadata"
ls -lL "$out"/rootfs/tarball/*.tar.xz "$out"/metadata/tarball/*.tar.xz
