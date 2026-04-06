{isNixOS ? false, ...}: {
  imports =
    [
      ./toolchains/node.nix
      ./toolchains/python.nix
      ./toolchains/fvm.nix
      ./toolchains/devbox.nix
      ./apps/llm-cli.nix
      ./apps/zed.nix
      ./jetbrains/default.nix
      ./jetbrains/android-studio.nix
    ]
    ++ (
      if isNixOS
      then [./base/os.nix]
      else []
    )
    ++ (
      if !isNixOS
      then [./base/home.nix]
      else []
    );
}
