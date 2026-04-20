{mkModHere, ...}:
mkModHere __curPos "Python toolchain" ({pkgs, ...}: let
  pythonEnv = pkgs.python312.withPackages (ps:
    with ps; [
      pip
      virtualenv
    ]);
in {
  hm = {
    home.packages = [pythonEnv];
  };
})
