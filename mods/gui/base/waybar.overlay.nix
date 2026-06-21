# Waybar Overlay to patch workspaces clicking issue with Hyprland 0.55+
_final: prev: {
  waybar =
    (prev.waybar.override {
      cavaSupport = false;
      runTests = false;
    }).overrideAttrs (_oldAttrs: {
      src = prev.fetchFromGitHub {
        owner = "Alexays";
        repo = "Waybar";
        rev = "05945748dccce28bf96d26d8f64a9e69a8dd49ba";
        sha256 = "09c6iqpyfi35g9ra9x0l7l58k9rsdzpskygmhxpv6w3wifc7fm77";
      };
      patches = [];
      doCheck = false;
    });
}
