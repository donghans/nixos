{pkgs, ...}: let
  # (목적: XML 파서로 defaultProjectLocation attribute 안전하게 패치)
  patchXml = pkgs.writeText "patch-jetbrains-xml.py" ''
    import sys, xml.etree.ElementTree as ET
    path, target = sys.argv[1], sys.argv[2]
    tree = ET.parse(path)
    root = tree.getroot()

    # GeneralSettings 컴포넌트만 대상으로 처리
    comp = next((c for c in root.findall("component") if c.get("name") == "GeneralSettings"), None)
    if comp is None:
        sys.exit(0)

    # 기존 항목 탐색 (name= 또는 key= 속성 모두 허용)
    entry = next(
        (child for child in comp if child.get("name") == "defaultProjectLocation" or child.get("key") == "defaultProjectLocation"),
        None,
    )
    if entry is not None:
        entry.set("value", target)
    else:
        opt = ET.SubElement(comp, "option")
        opt.set("name", "defaultProjectLocation")
        opt.set("value", target)

    if hasattr(ET, "indent"):
        ET.indent(tree)
    tree.write(path, encoding="unicode", xml_declaration=False)
  '';

  # (목적: 프로젝트 경로 정규화 및 UI 스케일 주입 래퍼)
  wrapJetbrainsPackage = pkg: binName: (pkgs.mkWrapper {
    inherit pkg binName;
    addFlags = ["-Dsun.java2d.uiScale=1.0"];

    # (목적: 커서 크기 고정 - XWayland 환경 대응)
    env = {
      XCURSOR_SIZE = "24";
      HYPRCURSOR_SIZE = "24";
    };

    # (목적: HOME 디렉터리 클러터링 방지 및 프로젝트 경로 강제 지정)
    run = ''
      PRJ_PARENT="$HOME/JetbrainsProjects"
      case "${binName}" in
        idea)           PRJ_NAME="IdeaProjects" ;;
        webstorm)       PRJ_NAME="WebstormProjects" ;;
        datagrip)       PRJ_NAME="DataGripProjects" ;;
        pycharm)        PRJ_NAME="PyCharmProjects" ;;
        android-studio) PRJ_NAME="AndroidStudioProjects" ;;
        *)              PRJ_NAME="''${binName}Projects" ;;
      esac

      TARGET_DIR="$PRJ_PARENT/$PRJ_NAME"
      mkdir -p "$TARGET_DIR"

      # JetBrains 설정 디렉터리 탐색 (버전별 폴더 대응)
      CONFIG_BASE="$HOME/.config/JetBrains"
      if [ -d "$CONFIG_BASE" ]; then
        for cfg in "$CONFIG_BASE/"*; do
          case "$(basename "$cfg")" in
            *[Ii][Dd][Ee][Aa]*|*[Ww][Ee][Bb][Ss][Tt][Oo][Rr][Mm]*|*[Dd][Aa][Tt][Aa][Gg][Rr][Ii][Pp]*|*[Pp][Yy][Cc][Hh][Aa][Rr][Mm]*|*[Aa][Nn][Dd][Rr][Oo][Ii][Dd]*)
              GEN_XML="$cfg/options/ide.general.xml"
              if [ -f "$GEN_XML" ]; then
                ${pkgs.python3}/bin/python3 ${patchXml} "$GEN_XML" "$TARGET_DIR"
              fi
              ;;
          esac
        done
      fi
    '';
  });
in {inherit wrapJetbrainsPackage;}
