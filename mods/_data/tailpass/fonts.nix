/*
  deploy/tailpass-fonts.conf(Noto Sans KR 서브셋을 sans-serif 폴백으로 등록)를 NixOS
  fonts.fontconfig.confPackages/fonts.packages로 등록한다. postinst.sh의 수동
  `fc-cache -f` 호출은 NixOS activation이 자동으로 대체하므로 불필요.

  GTK 네이티브 위젯(우클릭 컨텍스트 메뉴 등)의 한글 렌더링은 webview/egui 폰트 목록과
  무관하게 시스템 fontconfig에 의존하므로(deploy/tailpass-fonts.conf 주석 참조),
  daemon/authagent 둘 중 하나라도 활성화되면(App 자체가 설치되는 시점) 함께 등록한다.
*/
{ config, lib, pkgs, ... }:

let
  enabled = config.services.tailpass-daemon.enable || config.services.tailpass-authagent.enable;
  # daemon/authagent 모두 기본값이 동일 tailpassPackage이므로 어느 쪽이든 상관없다.
  pkg = config.services.tailpass-daemon.package;

  fontPkg = pkgs.runCommand "tailpass-notosanskr-fonts" { } ''
    mkdir -p $out/share/fonts/truetype/tailpass
    ln -s ${pkg}/share/fonts/truetype/tailpass/NotoSansKR-Regular-latin.ttf \
          $out/share/fonts/truetype/tailpass/
    ln -s ${pkg}/share/fonts/truetype/tailpass/NotoSansKR-Regular-korean.ttf \
          $out/share/fonts/truetype/tailpass/
  '';

  confPkg = pkgs.runCommand "tailpass-notosanskr-fontconfig" { } ''
    mkdir -p $out/etc/fonts/conf.d
    ln -s ${pkg}/share/tailpass/70-tailpass-notosanskr.conf \
          $out/etc/fonts/conf.d/70-tailpass-notosanskr.conf
  '';
in
{
  config = lib.mkIf enabled {
    fonts.packages = [ fontPkg ];
    fonts.fontconfig.confPackages = [ confPkg ];
  };
}
