{mkMod, ...}:
mkMod __curPos "CUPS Printing (Canon UFR II)" ({pkgs, ...}: {
  os = {
    services.printing = {
      enable = true;
      drivers = [pkgs.canon-cups-ufr2];
    };

    # Canon MF645Cx @ 192.168.11.246
    hardware.printers = {
      ensurePrinters = [
        {
          name = "Canon-MF645Cx";
          description = "Canon MF645Cx";
          deviceUri = "socket://192.168.11.246:9100";
          model = "CNRCUPSMF645CZK.ppd";
          ppdOptions.PageSize = "A4";
        }
      ];
      ensureDefaultPrinter = "Canon-MF645Cx";
    };
  };
})
