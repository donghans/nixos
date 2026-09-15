# Xarchiver를 압축파일 기본 연결 프로그램으로 지정.
# Nemo Actions(우클릭 "여기에 압축 풀기"/"압축하기...")는 안 쓰기로 결정 —
# GUI 앱을 직접 열어서 조작하는 방식으로만 사용.
#
# 참고 1: xarchiver GUI의 "Extract" 버튼이 기본으로 /tmp를 제안하는 문제는
# ~/.config/xarchiver/xarchiverrc의 `preferred_extract_dir=/tmp`가 원인
# (소스 확인: 비워두면 단일 압축 해제 다이얼로그는 아카이브 파일이 있는
# 디렉터리로 자동 폴백함 — src/extract_dialog.c의 xa_set_extract_dialog_options).
# 이 값은 xarchiver 자체가 Preferences 저장 시 덮어쓰는 파일이라 nix로
# 선언 관리하지 않고 수동으로 한 번 고쳐둠(Preferences > Advanced 탭에서도
# 직접 바꿀 수 있음). 다중 선택 압축해제 다이얼로그는 이 폴백이 없어 항상
# /tmp로 남는 xarchiver 자체 한계(패치 없이는 못 고침).
#
# 참고 2: zip 파일 비-ASCII 파일명 깨짐/"압축은 됐는데 에러 창" 문제
# (unzip 6.0의 local/central 헤더 필드 불일치 검증 버그, natspec 패치와도
# 무관 — vanilla unzip으로도 재현 확인됨)는 xarchiverrc의 `prefer_unzip=false`로
# 우회함. 이러면 xarchiver가 zip도 unzip 대신 7z(p7zip)로 처리함
# (src/main.c: prefer_unzip 꺼지고 7z/unar 중 하나라도 있으면 unzip 안 씀).
# 이 값도 앱이 Preferences 저장 시 덮어쓰므로 nix 관리 안 하고 수동 설정
# (Preferences > Archive > "Prefer unzip for zip files" 체크 해제, 재시작 필요).
# → 이 덕분에 mods.sys.utils.archive는 zip/unzip 없이 p7zip만 둠.
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Xarchiver (압축파일 기본 연결 프로그램)" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.xarchiver];

    # xarchiver 패키지의 .desktop(Icon=xarchiver)을 덮어써서 창/작업표시줄
    # 아이콘 교체. ~/.local/share/applications가 우선순위상 앞서서 이걸로 대체됨.
    # 다른 아이콘으로 바꾸려면 icon 값만 교체(아이콘 테마: Papirus-Dark).
    xdg.desktopEntries.xarchiver = {
      name = "Xarchiver";
      genericName = "Archive manager";
      comment = "Create, extract and modify archives";
      icon = "archive-manager";
      exec = "xarchiver %f";
      terminal = false;
      categories = ["GTK" "Utility" "Archiving" "Compression"];
    };

    # 압축파일 더블클릭 시 기본으로 xarchiver가 열리도록 연결.
    xdg.mimeApps.defaultApplications = let
      archiveMimeTypes = [
        "application/zip"
        "application/x-7z-compressed"
        "application/vnd.rar"
        "application/x-rar"
        "application/x-tar"
        "application/x-compressed-tar"
        "application/gzip"
        "application/x-bzip"
        "application/x-bzip2"
        "application/x-bzip-compressed-tar"
        "application/x-bzip2-compressed-tar"
        "application/x-xz"
        "application/x-xz-compressed-tar"
        "application/x-lzma"
        "application/x-cpio"
        "application/x-arj"
        "application/java-archive"
        "application/vnd.ms-cab-compressed"
      ];
    in
      builtins.listToAttrs (map (n: {
          name = n;
          value = "xarchiver.desktop";
        })
        archiveMimeTypes);
  };
})
