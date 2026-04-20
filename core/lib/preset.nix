# core/lib/preset.nix
# 프리셋 커버리지 체크 모듈 팩토리
#
# 사용법 (flake.nix에서 per-host로 생성):
#   coverageModule = { config, options, lib, ... }:
#     import ./lib/preset.nix {
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
    if builtins.isBool val
    then ["${prefix}.enable"]
    else if isAttrs val
    then
      concatLists (mapAttrsToList (
          k: v:
            if k == "enable" && builtins.isBool v
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

  # == 형제 옵션 완전성 검사 ==
  # 하나라도 명시 시 같은 그룹(공통 부모) 전체를 명시해야 함
  getGroup = path: let
    parts = splitString "." path;
  in
    concatStringsSep "." (take (length parts - 2) parts);

  checkableOptions =
    filter (
      opt:
        !(isExcluded opt) && !(elem opt explicitOptional)
    )
    declaredOptions;

  groupedOptions = groupBy getGroup checkableOptions;

  incompleteGroups =
    filterAttrs (
      _group: members: let
        explicitCount = length (filter (m: presetCoveredSet ? ${m}) members);
      in
        length members > 1 && explicitCount > 0 && explicitCount < length members
    )
    groupedOptions;

  incompleteMessages =
    mapAttrsToList (
      group: members: let
        missing = filter (m: !(presetCoveredSet ? ${m})) members;
      in "${group}: 누락 → ${concatStringsSep ", " missing}"
    )
    incompleteGroups;
in {
  config.assertions = [
    # == Coverage Check: 새 mods 항목 누락 감지 ==
    {
      assertion = uncovered == [];
      message = ''
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        [Mods Coverage] 프리셋에 등록되지 않은 모드 옵션이 있습니다.

          누락된 옵션:
            ${concatStringsSep "\n        " uncovered}

          발생 원인:
            core/lib/workspace-options.nix에 새 enable 옵션이 추가됐지만
            hosts/_preset.${presetName}.toml에 해당 항목이 없을 때 발생합니다.

          해결 방법 (둘 중 하나):
            1. hosts/_preset.${presetName}.toml에 추가 (기본값 선언):
                 [mods.<도메인>]
                 <기능> = false   # 비활성화 기본값, 또는 true
            2. 의도적으로 프리셋 밖에서 관리할 경우:
                 hosts/_preset.${presetName}.toml의 [explicitOptional] paths에 추가
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      '';
    }
    # == Sibling Coverage Check: 형제 옵션 완전성 검사 ==
    {
      assertion = incompleteGroups == {};
      message = ''
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        [Mods Coverage] 같은 그룹에서 일부 옵션만 프리셋에 명시되었습니다.

          불완전한 그룹 (누락된 항목):
            ${concatStringsSep "\n        " incompleteMessages}

          발생 원인:
            hosts/_preset.${presetName}.toml에서 [mods.x.y] 섹션 내
            일부 옵션만 기재하고 나머지를 누락했을 때 발생합니다.
            같은 그룹 안에서 하나라도 명시하면 나머지도 전부 명시해야 합니다.

          해결 방법 (둘 중 하나):
            1. hosts/_preset.${presetName}.toml에서 누락된 형제 옵션도 추가
            2. 의도적 제외라면 [explicitOptional] paths에 추가
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      '';
    }
  ];
}
