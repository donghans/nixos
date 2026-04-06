{isNixOS ? false, ...} @ args: {
  imports = [
    (import ./base/default.nix args)
  ];
}
