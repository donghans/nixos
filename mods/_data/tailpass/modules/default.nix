/*
  services.tailpass-daemon / services.tailpass-authagent / services.tailpass-sshagent
  NixOS 모듈 묶음. flake.nix가 nixosModules.default로 노출한다.
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
    ./sshagent.nix
    ../native-messaging-host.nix
    ../fonts.nix
  ];
}
