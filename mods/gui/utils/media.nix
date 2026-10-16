# 이미지·영상·오디오 보기/재생 — 비교 측정과 특징은 _docs/content/explanation/media-apps.md
#
# 역할 분담 (런처 wofi 에는 "직접 골라 쓰는 것"만 보이게 하고, 더블클릭으로 열리는 기본 프로그램은 숨김):
#   이미지   기본: imv-dir  (런처에서 숨김. imv 는 파일 하나를 주면 그 파일만 열어서, 폴더의 다음/이전 사진으로 넘기려면
#                            폴더를 통째로 여는 imv-dir 가 필요함 — 실제로 imv=[1/1], imv-dir=[2/3] 으로 확인)
#            선택: swayimg (런처에 보임, Thunar 우클릭 "swayimg로 열기". 폴더 단위 갤러리가 장점)
#   영상/오디오 기본: mpv (런처에서 숨김, VA-API 하드웨어 디코딩)
#            선택: VLC (런처에 보임, Thunar 우클릭 "VLC로 열기")
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "미디어 (imv, swayimg, mpv, vlc)" ({
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

  # 파일 없이 켜면(런처) 사진 폴더(하위 폴더 포함)를 보여줌. swayimg 는 인자가 없으면 현재 폴더(= 홈)에서 이미지를 찾는데
  # 없으면 바로 종료하기 때문. (Pictures 에는 이미지가 Screenshots/ 같은 하위 폴더에 있어서 하위 폴더도 읽음)
  swayimgOpen = pkgs.writeShellScriptBin "swayimg-open" ''
    [ $# -gt 0 ] || set -- -c list.recursive=yes "$HOME/Pictures"
    exec ${pkgs.swayimg}/bin/swayimg "$@"
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
    home.packages = [pkgs.imv pkgs.swayimg swayimgOpen pkgs.vlc];

    # 영상: VA-API 하드웨어 디코딩(intel-media-driver 는 hosts/ 의 hardware.graphics.extraPackages). 같은 영상에서 CPU 약 절반
    programs.mpv = {
      enable = true;
      config.hwdec = "vaapi";
    };

    # swayimg: 파일 하나를 열어도 같은 폴더 전체를 넘겨볼 수 있게 (기본은 그 파일만 염. 실제로 확인)
    xdg.configFile."swayimg/config".text = ''
      [list]
      all = yes
    '';

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
      # swayimg 는 패키지에서 NoDisplay 라 런처에 보이게 다시 정의
      swayimg = {
        name = "Swayimg";
        genericName = "Image viewer";
        icon = "swayimg";
        exec = "swayimg-open %F";
        mimeType = imageMimeTypes;
        terminal = false;
        categories = ["Graphics" "Viewer"];
      };
    };

    # Thunar 우클릭(사용자 지정 동작). 폴더를 우클릭해 갤러리/재생목록으로 여는 용도
    xdg.configFile."Thunar/uca.xml".text = ''
      <?xml version="1.0" encoding="UTF-8"?>
      <actions>
      ${ucaAction "1792143897495107-1" "utilities-terminal" "Open Terminal Here" "exo-open --working-directory %f --launch TerminalEmulator" "<directories/>"}
      ${ucaAction "1792143897495107-2" "image-x-generic" "swayimg로 열기" "swayimg-open %F" "<directories/>\n\t<image-files/>"}
      ${ucaAction "1792143897495107-3" "vlc" "VLC로 열기" "vlc %F" "<directories/>\n\t<audio-files/>\n\t<video-files/>"}
      </actions>
    '';
  };
})
