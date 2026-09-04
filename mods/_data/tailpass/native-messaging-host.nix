/*
  deploy/com.tailpass.daemon.json의 path가 FHS 경로(/usr/local/bin/tailpass-daemon-nm)로
  하드코딩되어 있어 Nix store 경로 배포에는 그대로 못 쓴다. services.tailpass-daemon이
  활성화되면(Extension이 daemon과 통신하려면 daemon이 필수이므로 여기 종속) 그 경로만
  치환한 매니페스트를 새로 생성해 Chrome/Chromium이 읽는 두 경로에 동시 배치한다.

  [문서에 명시할 확인 필요 사항] 아래 두 경로(/etc/opt/chrome/, /etc/chromium/)는 조사
  기준 통상적인 배포판 관례이나, 실제 브라우저 버전/배포 채널에 따라 다를 수 있어
  실기 NixOS에서 재확인이 필요하다.
*/
{ config, lib, pkgs, ... }:

let
  cfg = config.services.tailpass-daemon;

  manifest = pkgs.writeText "com.tailpass.daemon.json" (builtins.toJSON {
    name = "com.tailpass.daemon";
    description = "Tailpass Daemon Native Messaging Host";
    path = "${cfg.package}/bin/tailpass-daemon-nm";
    type = "stdio";
    allowed_origins = [ "chrome-extension://bpiokcapiggifjicjhmbbpfkieogfohd/" ];
  });
in
{
  config = lib.mkIf cfg.enable {
    environment.etc = {
      "opt/chrome/native-messaging-hosts/com.tailpass.daemon.json".source = manifest;
      "chromium/native-messaging-hosts/com.tailpass.daemon.json".source = manifest;
    };
  };
}
