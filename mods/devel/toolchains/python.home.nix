{pkgs, ...}: let
  # (목적: 향후 Python 바이너리 래핑이 필요할 경우 여기서 정의)
  # wrapPython = pkg: ...;
  pythonEnv = pkgs.python312.withPackages (ps:
    with ps; [
      pip
      virtualenv
    ]);
in {
  home.packages = [
    pythonEnv
  ];
}
