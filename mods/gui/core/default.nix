{isNixOS ? false, ...}: {
  imports =
    (
      if isNixOS
      then [./os.nix]
      else []
    )
    ++ (
      if !isNixOS
      then [./home.nix]
      else []
    );
}
