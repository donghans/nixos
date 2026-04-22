{mkPartOf, pkgs, ...}:
mkPartOf "mods.sys.base" ({
  config,
  lib,
  ...
}: let
  isAws = config.workspace.cloudProvider == "aws";
in {
  os = lib.mkIf isAws {
    services.amazon-ssm-agent.enable = true;
    boot.kernelParams = ["console=ttyS0,115200n8"];
    environment.systemPackages = [pkgs.awscli2];
  };
})
