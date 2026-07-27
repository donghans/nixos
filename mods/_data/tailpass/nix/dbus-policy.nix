/*
  authagent D-Bus 시스템 버스 정책 + 서비스 활성화 파일을 담는 작은 파생물.
  services.dbus.packages에 등록하면 NixOS의 dbus.nix 모듈이
  «pkg»/share/dbus-1/system.d와 «pkg»/share/dbus-1/system-services를 자동으로 스캔한다
  (deploy/it.bitstep.tailpass.AuthAgent1.conf/.service를 postinst.sh가 셸로
  /etc/dbus-1/system.d에 복사하던 것의 NixOS 대체).

  .conf는 원본 그대로 재사용한다. .service는 Exec=/usr/local/bin/tailpass-authagent가
  FHS 경로로 하드코딩되어 있어, 실제 패키지의 Nix store 경로로 치환한 버전을 새로 쓴다
  — 이게 원본 deploy/ 파일 내용을 손대야 하는 유일한 지점.
*/
{ lib, runCommand, tailpassPackage }:

runCommand "tailpass-authagent-dbus-policy" { } ''
  mkdir -p $out/share/dbus-1/system.d $out/share/dbus-1/system-services

  install -m644 ${./it.bitstep.tailpass.AuthAgent1.conf} \
    $out/share/dbus-1/system.d/it.bitstep.tailpass.AuthAgent1.conf

  cat > $out/share/dbus-1/system-services/it.bitstep.tailpass.AuthAgent1.service <<EOF
  [D-BUS Service]
  Name=it.bitstep.tailpass.AuthAgent1
  Exec=${tailpassPackage}/bin/tailpass-authagent
  User=tailpass-auth
  SystemdService=tailpass-authagent.service
  EOF
''
