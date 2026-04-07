{isNixOS ? false, ...}: {
  imports =
    [
      ./fcitx.nix
      ./polkit.nix
      ./xdg.nix
    ]
    ++ (
      if isNixOS
      then [./os.nix ./greeter.nix]
      else []
    )
    ++ (
      if !isNixOS
      then [./home.nix]
      else []
    );
}
