{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Nemo archive context menu (file-roller)" ({
  config,
  pkgs,
  ...
}: {
  hm = {
    assertions = [
      {
        assertion = config.mods.sys.utils.archive.enable;
        message = "mods.gui.utils.nemo-fileroller는 mods.sys.utils.archive.enable = true 가 필요합니다 (zip/7z 백엔드)";
      }
    ];

    home.packages = [pkgs.nemo-fileroller pkgs.file-roller];

    # Nemo는 확장 디렉터리를 하나만 인식하므로(NEMO_EXTENSION_DIR),
    # 다른 nemo 확장을 추가로 쓸 경우 symlinkJoin으로 합쳐서 지정해야 함.
    home.sessionVariables.NEMO_EXTENSION_DIR = "${pkgs.nemo-fileroller}/lib/nemo/extensions-3.0";
  };
})
