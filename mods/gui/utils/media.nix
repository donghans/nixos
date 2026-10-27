# 이미지·영상·오디오 보기/재생 — 비교 측정과 특징은 mods/_tools/media-bench/README.md
#
# 역할 분담 (런처 wofi 에는 "직접 골라 쓰는 것"만 보이게 하고, 더블클릭으로 열리는 기본 프로그램은 숨김):
#   이미지   기본: imv-dir  (런처에서 숨김. imv 는 파일 하나를 주면 그 파일만 열어서, 폴더의 다음/이전 사진으로 넘기려면
#                            폴더를 통째로 여는 imv-dir 가 필요함 — 실제로 imv=[1/1], imv-dir=[2/3] 으로 확인)
#            선택: loupe (런처에 보임, 자르기/회전/뒤집기 편집 가능. 폴더를 인자로 못 받아서 Thunar 우클릭 "Open in Loupe" 는
#                         loupe-open 래퍼가 폴더를 이미지 파일 목록으로 풀어서 넘김. swayimg 와 비교는 문서 참고)
#   영상/오디오 기본: mpv (런처에서 숨김, VA-API 하드웨어 디코딩)
#            선택: VLC (런처에 보임, Thunar 우클릭 "Open in VLC")
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "미디어 (imv, loupe, mpv, vlc)" ({
  pkgs,
  lib,
  ...
}: let
  # imv-dir.desktop 이 선언한 형식
  imageMimeTypes = ["image/x-farbfeld" "image/tiff" "image/tiff-fx" "image/png" "image/x-png" "image/jpeg" "image/jpg" "image/pjpeg" "image/svg+xml" "image/gif" "image/bmp" "image/x-bmp" "image/heif" "image/avif" "image/jxl" "image/webp" "image/qoi"];

  # mpv.desktop 이 선언한 형식 (오디오/영상/재생목록)
  mpvMimeTypes = lib.filter (s: s != "") (lib.concatMap (lib.splitString " ") (lib.splitString "\n" ''
    application/mxf application/ogg application/sdp application/smil application/streamingmedia
    application/vnd.apple.mpegurl application/vnd.ms-asf application/vnd.rn-realmedia
    application/vnd.rn-realmedia-vbr application/x-cue application/x-extension-m4a
    application/x-extension-mp4 application/x-matroska application/x-mpegurl application/x-ogg
    application/x-ogm application/x-ogm-audio application/x-ogm-video application/x-shorten
    application/x-smil application/x-streamingmedia audio/3gpp audio/3gpp2 audio/aac audio/ac3
    audio/aiff audio/AMR audio/amr-wb audio/dv audio/eac3 audio/flac audio/m3u audio/m4a audio/mp1
    audio/mp2 audio/mp3 audio/mp4 audio/mpeg audio/mpeg2 audio/mpeg3 audio/mpegurl audio/mpg
    audio/musepack audio/ogg audio/opus audio/rn-mpeg audio/scpls audio/vnd.dolby.heaac.1
    audio/vnd.dolby.heaac.2 audio/vnd.dts audio/vnd.dts.hd audio/vnd.rn-realaudio audio/vnd.wave
    audio/vorbis audio/wav audio/webm audio/x-aac audio/x-adpcm audio/x-aiff audio/x-ape
    audio/x-m4a audio/x-matroska audio/x-mp1 audio/x-mp2 audio/x-mp3 audio/x-mpegurl audio/x-mpg
    audio/x-ms-asf audio/x-ms-wma audio/x-musepack audio/x-pls audio/x-pn-au audio/x-pn-realaudio
    audio/x-pn-wav audio/x-pn-windows-pcm audio/x-realaudio audio/x-scpls audio/x-shorten
    audio/x-tta audio/x-vorbis audio/x-vorbis+ogg audio/x-wav audio/x-wavpack video/3gp video/3gpp
    video/3gpp2 video/avi video/divx video/dv video/fli video/flv video/mkv video/mp2t video/mp4
    video/mp4v-es video/mpeg video/msvideo video/ogg video/quicktime video/vnd.avi video/vnd.divx
    video/vnd.mpegurl video/vnd.rn-realvideo video/webm video/x-avi video/x-flc video/x-flic
    video/x-flv video/x-m4v video/x-matroska video/x-mpeg2 video/x-mpeg3 video/x-ms-afs
    video/x-ms-asf video/x-msvideo video/x-ms-wmv video/x-ms-wmx video/x-ms-wvxvideo video/x-ogm
    video/x-ogm+ogg video/x-theora video/x-theora+ogg
  ''));

  # loupe 의 이미지 로더(glycin)는 bubblewrap 샌드박스에서 돌아가는데, bwrap 은 setuid 가 아니면서 capability 를 가진 채로는
  # "Unexpected capabilities but not setuid" 로 거부하고 종료 코드 1 로 끝남 → loupe 가 "Could not Load Image" 를 냄.
  # NixOS 의 Hyprland 래퍼가 cap_sys_nice=ep 라 Hyprland 가 띄운 모든 프로세스(Thunar 데몬, 런처, waybar…)가 CAP_SYS_NICE 를
  # ambient 로 물려받음(/proc/<pid>/status 의 CapAmb 로 확인). 터미널 등 권한 없는 경로에서는 열리고 Thunar/런처에서는 안 열렸던 이유.
  # → loupe 를 실행하기 직전에 ambient capability 를 비움(exec 후 권한이 사라짐). PATH 의 loupe 를 이 래퍼가 가리도록 hiPrio.
  loupeNoCap = lib.hiPrio (pkgs.writeShellScriptBin "loupe" ''
    exec ${pkgs.util-linux}/bin/setpriv --ambient-caps=-all ${pkgs.loupe}/bin/loupe "$@"
  '');

  # loupe 는 폴더를 인자로 받으면 창이 뜨지 않음(실측). 폴더는 안의 이미지 파일로 풀어서 넘김(이름순). 인자가 없으면 그대로 빈 창("Open Files…")
  loupeOpen = pkgs.writeShellScriptBin "loupe-open" ''
    args=()
    for a in "$@"; do
      if [ -d "$a" ]; then
        while IFS= read -r -d $'\0' f; do args+=("$f"); done < <(
          ${pkgs.findutils}/bin/find "$a" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.gif' \
            -o -iname '*.webp' -o -iname '*.bmp' -o -iname '*.tif' -o -iname '*.tiff' -o -iname '*.svg' -o -iname '*.avif' \
            -o -iname '*.heic' -o -iname '*.heif' -o -iname '*.jxl' -o -iname '*.ico' -o -iname '*.qoi' \) -print0 | sort -zV)
      else
        args+=("$a")
      fi
    done
    exec ${loupeNoCap}/bin/loupe "''${args[@]}"
  '';

  ucaAction = id: icon: name: command: types: ''
    <action>
    	<icon>${icon}</icon>
    	<name>${name}</name>
    	<submenu></submenu>
    	<unique-id>${id}</unique-id>
    	<command>${command}</command>
    	<description></description>
    	<range></range>
    	<patterns>*</patterns>
    	<startup-notify/>
    	${types}
    </action>
  '';
in {
  hm = {
    home.packages = [pkgs.imv pkgs.loupe loupeNoCap loupeOpen pkgs.vlc];

    # 영상: VA-API 하드웨어 디코딩(intel-media-driver 는 hosts/ 의 hardware.graphics.extraPackages). 같은 영상에서 CPU 약 절반
    programs.mpv = {
      enable = true;
      config = {
        hwdec = "vaapi";
        # 파일 하나를 열어도 같은 폴더의 같은 종류(오디오는 오디오끼리) 파일이 재생목록이 되어 이전/다음(< >)이 됨.
        # 기본(no)은 파일 하나면 재생목록도 하나뿐. 실측: b.flac 을 열면 [a.mp3, b.flac, c.mp3] (filter 는 png 까지 섞임)
        autocreate-playlist = "same";
      };
    };

    xdg.mimeApps.defaultApplications =
      lib.genAttrs imageMimeTypes (_: "imv-dir.desktop")
      // lib.genAttrs mpvMimeTypes (_: "mpv.desktop");

    xdg.desktopEntries = {
      # 기본 프로그램은 런처에서 숨김 (패키지의 mpv.desktop 을 같은 이름으로 덮어쓰므로 형식 선언도 다시 적음)
      mpv = {
        name = "mpv Media Player";
        genericName = "Multimedia player";
        icon = "mpv";
        exec = "mpv --player-operation-mode=pseudo-gui -- %U";
        mimeType = mpvMimeTypes;
        terminal = false;
        noDisplay = true;
        categories = ["AudioVideo" "Audio" "Video" "Player"];
      };
    };

    # Thunar 우클릭(사용자 지정 동작). 폴더를 우클릭해 이미지/재생목록으로 여는 용도
    xdg.configFile."Thunar/uca.xml".text = ''
      <?xml version="1.0" encoding="UTF-8"?>
      <actions>
      ${ucaAction "1792143897495107-1" "utilities-terminal" "Open Terminal Here" "exo-open --working-directory %f --launch TerminalEmulator" "<directories/>"}
      ${ucaAction "1792143897495107-2" "image-x-generic" "Open in Loupe" "loupe-open %F" "<directories/>\n\t<image-files/>"}
      ${ucaAction "1792143897495107-4" "applications-graphics" "Annotate with Satty" "${pkgs.satty}/bin/satty --filename %f" "<image-files/>"}
      ${ucaAction "1792143897495107-3" "vlc" "Open in VLC" "vlc %F" "<directories/>\n\t<audio-files/>\n\t<video-files/>"}
      </actions>
    '';
  };
})
