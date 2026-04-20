{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Zed editor" ({unstable, ...}: {
  hm = {
    home.packages = [unstable.zed-editor];
  };
})
