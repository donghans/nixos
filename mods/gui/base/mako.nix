{mkPartOf, ...}:
mkPartOf "mods.gui" (_: {
  hm = {
    services.mako.enable = true;

    services.mako.settings = {
      default-timeout = 5000; # ms
      background-color = "#282a36";
    };
  };
})
