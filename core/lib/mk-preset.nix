# core/lib/mk-preset.nix
# 프리셋 커버리지 체크 모듈 팩토리
#
# 사용법 (flake.nix에서 per-host로 생성):
#   coverageModule = { config, options, lib, ... }:
#     import ./lib/mk-preset.nix {
#       inherit lib config options;
#       presetName      = resolved.preset;
#       presetsJsonPath = ./presets.json;
#     };
{
  lib,
  options,
  presetName,
  presetsJsonPath,
  # 커버리지 체크에서 제외할 mods 경로 접두사 목록
  # (예: root@hostname는 gui/devel 옵션을 선언하지 않음)
  excludePrefixes ? [],
}:
with lib; let
  presetsRaw = builtins.fromJSON (builtins.readFile presetsJsonPath);
  preset = presetsRaw.${presetName}.mods;
  explicitOptional = presetsRaw.${presetName}.explicitOptional or [];

  # == JSON에서 커버된 .enable 경로 추출 ==
  # {"sys": {"base": true}}         → ["mods.sys.base.enable"]
  # {"gui": {"enable": true, ...}}  → ["mods.gui.enable", ...]
  jsonToPaths = prefix: val:
    if builtins.isBool val && val
    then ["${prefix}.enable"]
    else if isAttrs val
    then
      concatLists (mapAttrsToList (
          k: v:
            if k == "enable" && builtins.isBool v && v
            then ["${prefix}.enable"]
            else jsonToPaths "${prefix}.${k}" v
        )
        val)
    else [];
  presetCovered = jsonToPaths "mods" preset;
  presetCoveredSet = listToAttrs (map (p: {
      name = p;
      value = true;
    })
    presetCovered);

  # == options.mods에서 선언된 모든 .enable 경로 추출 ==
  findEnableOptions = prefix: attrs:
    concatLists (mapAttrsToList (
        name: val:
          if name == "enable" && isOption val
          then ["${prefix}.enable"]
          else if isAttrs val && !(isOption val)
          then findEnableOptions "${prefix}.${name}" val
          else []
      )
      attrs);
  declaredOptions = findEnableOptions "mods" options.mods;

  # == 조상 경로 활성화 여부 확인 ==
  # 부모 도메인이 preset에 포함되면 하위 옵션은 자동 커버로 간주.
  # 예: "mods.devel.enable"이 presetCovered → "mods.devel.node.enable" 자동 통과
  isAncestorCovered = path: let
    parts = splitString "." path;
    ancestorEnables = map (
      n:
        (concatStringsSep "." (take n parts)) + ".enable"
    ) (range 1 (length parts - 2));
  in
    any (p: presetCoveredSet ? ${p}) ancestorEnables;

  isExcluded = opt: any (prefix: hasPrefix "${prefix}." opt) excludePrefixes;

  uncovered =
    filter (
      opt:
        !(presetCoveredSet ? ${opt})
        && !(isAncestorCovered opt)
        && !(elem opt explicitOptional)
        && !(isExcluded opt)
    )
    declaredOptions;
in {
  config.assertions = [
    # == Coverage Check: 새 mods 항목 누락 감지 ==
    {
      assertion = uncovered == [];
      message = ''
        [Mods Coverage] workspace-options에 선언됐으나 preset에 없는 옵션:
          ${concatStringsSep "\n  " uncovered}
        → ${presetName}.toml에 추가하거나,
          의도적 제외라면 ${presetName}.toml의 [explicitOptional] paths에 추가하세요.
      '';
    }
  ];
}
