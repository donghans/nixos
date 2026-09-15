{mkMod, ...}:
mkMod __curPos "sshpass (non-interactive SSH password auth)" ({pkgs, ...}: {
  os.environment.systemPackages = with pkgs; [sshpass];
  hm.home.packages = with pkgs; [sshpass];
})
