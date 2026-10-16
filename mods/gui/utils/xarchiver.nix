# Xarchiver를 압축파일 기본 연결 프로그램으로 지정.
# Nemo Actions(우클릭 "여기에 압축 풀기"/"압축하기...")는 안 쓰기로 결정 —
# GUI 앱을 직접 열어서 조작하는 방식으로만 사용.
#
# 참고 1: xarchiver GUI의 "Extract" 버튼이 기본으로 /tmp를 제안하는 문제는
# ~/.config/xarchiver/xarchiverrc의 `preferred_extract_dir=/tmp`가 원인
# (src/extract_dialog.c의 xa_set_extract_dialog_options: 이 값이 비어 있으면 단일 압축 해제
# 다이얼로그는 아카이브 파일이 있는 디렉터리로 자동 폴백함. 화면에서 직접 확인함).
# 다중 선택 압축해제 다이얼로그(xa_multi_extract_dialog)는 비어 있으면 /tmp 가 코드에
# 하드코딩되어 있어 설정으로는 못 고침 → 아래 home.packages 의 소스 패치로 첫 아카이브 폴더를 기본값으로 함.
#
# 참고 2: zip 파일 비-ASCII 파일명 깨짐/"압축은 됐는데 에러 창" 문제
# (unzip 6.0의 local/central 헤더 필드 불일치 검증 버그, natspec 패치와도
# 무관 — vanilla unzip으로도 재현 확인됨)는 xarchiverrc의 `prefer_unzip=false`로
# 우회함. 이러면 xarchiver가 zip도 unzip 대신 7z(p7zip)로 처리함
# (src/main.c: prefer_unzip 꺼지고 7z/unar 중 하나라도 있으면 unzip 안 씀).
# → 이 덕분에 mods.sys.utils.archive는 zip/unzip 없이 p7zip만 둠.
#
# 위 두 값은 xarchiver 가 종료할 때마다 자기 설정 파일을 통째로 다시 쓰고, 설정 파일이 없거나 읽히지
# 않으면 기본값(/tmp, prefer_unzip=true)으로 새로 만들기 때문에 한 번 손으로 고쳐 두면 되돌아간다.
# 파일 전체를 선언(읽기 전용 링크)하면 앱이 저장하지 못하므로, 아래 home.activation 이
# 홈 활성화(nixup)마다 이 두 키만 맞춘다 (파일이 없으면 기본 세트에서 두 값만 바꿔 생성).
# (xarchiver 가 실행 중일 때 활성화하면 종료 시 앱 값으로 다시 덮이므로, 그땐 다음 활성화 때 다시 맞춰짐)
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Xarchiver (압축파일 기본 연결 프로그램)" ({
  pkgs,
  lib,
  ...
}: let
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
in {
  hm = {
    # 다중 선택 압축 해제(Multi-Extract) 다이얼로그의 대상 경로가 /tmp 로 고정되던 것을 패치:
    # 첫 번째로 추가한 아카이브가 있는 폴더를 기본 대상으로 쓰고, 다이얼로그를 닫으면 비움
    # (원본은 설정이 비어 있으면 /tmp 로 하드코딩 — 설정 파일로는 못 바꿈)
    home.packages = [
      (pkgs.xarchiver.overrideAttrs (old: {
        postPatch =
          (old.postPatch or "")
          + ''
            substituteInPlace src/extract_dialog.c \
              --replace-fail $'\tmulti_extract->nr_total++;\n\tg_free(file_utf8);' \
              $'\tmulti_extract->nr_total++;\n\tif (multi_extract->nr_total == 1 && !*gtk_entry_get_text(GTK_ENTRY(multi_extract->destination_path_entry)))\n\t\tgtk_entry_set_text(GTK_ENTRY(multi_extract->destination_path_entry), path_utf8);\n\tg_free(file_utf8);' \
              --replace-fail $'\tgtk_list_store_clear(multi_extract->liststore);\n' \
              $'\tgtk_list_store_clear(multi_extract->liststore);\n\tgtk_entry_set_text(GTK_ENTRY(multi_extract->destination_path_entry), "");\n'
          '';
      }))
    ];

    # xarchiver 패키지의 .desktop(Icon=xarchiver)을 덮어써서 창/작업표시줄
    # 아이콘 교체. ~/.local/share/applications가 우선순위상 앞서서 이걸로 대체됨.
    # 다른 아이콘으로 바꾸려면 icon 값만 교체(아이콘 테마: Papirus-Dark).
    xdg.desktopEntries.xarchiver = {
      name = "Xarchiver";
      genericName = "Archive manager";
      comment = "Create, extract and modify archives";
      icon = "archive-manager";
      exec = "xarchiver %f";
      mimeType = archiveMimeTypes; # (Thunar 등이 이 앱을 압축 처리기로 인식하는 데 필요)
      terminal = false;
      categories = ["GTK" "Utility" "Archiving" "Compression"];
    };

    # 압축파일 더블클릭 시 기본으로 xarchiver가 열리도록 연결.
    xdg.mimeApps.defaultApplications = builtins.listToAttrs (map (n: {
        name = n;
        value = "xarchiver.desktop";
      })
      archiveMimeTypes);

    # (이유) thunar-archive-plugin 은 g_app_info_get_all_for_type 으로 "해당 형식을 처리한다고 선언한" 앱의
    #        desktop-id 로 <id>.tap 을 찾음. 위 desktopEntries 가 패키지의 xarchiver.desktop 을 덮어쓰면서
    #        MimeType= 이 없어지면 "No suitable archive manager found" 가 되므로 형식을 연결로도 선언해 둠.
    xdg.mimeApps.associations.added = builtins.listToAttrs (map (n: {
        name = n;
        value = ["xarchiver.desktop"];
      })
      archiveMimeTypes);

    # xarchiverrc 의 두 키(preferred_extract_dir, prefer_unzip)만 활성화 때마다 맞춤 — 위 헤더 주석 참고
    home.activation.xarchiverPrefs = lib.hm.dag.entryAfter ["writeBoundary"] ''
      rc="$HOME/.config/xarchiver/xarchiverrc"
      if [ -n "''${DRY_RUN:-}" ]; then
        echo "xarchiverrc: dry-run (변경 없음)"
      else
        mkdir -p "$(dirname "$rc")"
        if [ ! -f "$rc" ]; then
          cat > "$rc" <<'RC'
      [xarchiver]
      preferred_format=0
      prefer_unzip=false
      confirm_deletion=true
      sort_filename_content=false
      advanced_isearch=true
      auto_expand=true
      store_output=false
      icon_size=2
      show_archive_comment=false
      show_sidebar=true
      show_location_bar=true
      show_toolbar=true
      preferred_custom_cmd=
      preferred_temp_dir=/tmp
      preferred_extract_dir=
      allow_sub_dir=0
      extended_dnd=1
      ensure_directory=true
      overwrite=false
      full_path=2
      touch=false
      fresh=false
      update=false
      store_path=false
      updadd=true
      freshen=false
      recurse=true
      solid_archive=false
      remove_files=false
      RC
        else
          set_key() {
            if ${pkgs.gnugrep}/bin/grep -q "^$1=" "$rc"; then
              ${pkgs.gnused}/bin/sed -i "s|^$1=.*|$1=$2|" "$rc"
            else
              ${pkgs.gnused}/bin/sed -i "/^\[xarchiver\]/a $1=$2" "$rc"
            fi
          }
          set_key preferred_extract_dir ""
          set_key prefer_unzip false
        fi
      fi
    '';
  };
})
