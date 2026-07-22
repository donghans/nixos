/*
  services.tailpass-daemon / services.tailpass-authagent NixOS 모듈 묶음.

  /home/donghans/tailpass/deploy/nix/에서 그대로 vendoring한 사본이다(flake input
  없이 pure eval 안에서 쓰기 위함 — tailpass 저장소 자체를 flake input으로 끌어오면
  target/ 39GB가 통째로 복사되거나 --impure가 필요해짐). tailpass 쪽 deploy/nix/*.nix가
  바뀌면 이 디렉터리(../ 포함 mods/_data/tailpass/)를 수동으로 다시 복사해야 한다.
*/
{ tailpassPackage }:

{ ... }:

{
  # daemon.nix/authagent.nix는 tailpassPackage를 일반 모듈 인자로 받는다 — 여기서
  # _module.args로 주입하면 NixOS 모듈 시스템이 두 모듈을 평가할 때 자동으로 넘겨준다.
  _module.args.tailpassPackage = tailpassPackage;

  imports = [
    ./daemon.nix
    ./authagent.nix
    ../native-messaging-host.nix
    ../fonts.nix
  ];
}
