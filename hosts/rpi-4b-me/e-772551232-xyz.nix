{...}: {
  imports = [
    ../_lib/headscale.nix
  ];

  headscale = {
    domain = "e.772551232.xyz";
    baseDomain = "i.772551232.xyz";
    staticIpv4 = "192.168.0.2";
    enableDerp = true;
    derpRegionId = 999;
    derpRegionCode = "kr-rpi";
    derpRegionName = "Korea (RPi4b)";

    # RPi 전용 DB 튜닝 및 v6 Prefix (이전 headscale.nix 공통화 시 추가했던 기능 복구)
    sqliteWriteAheadLog = true;
    sqliteWalAutocheckpoint = 1000;
    gormPrepareStmt = true;
    gormParameterizedQueries = true;
    gormSkipErrRecordNotFound = true;
    gormSlowThreshold = 1000;
    prefixesV6 = "fd7a:115c:a1e0::/48";
    unixSocket = "/var/run/headscale/headscale.sock";
    unixSocketPermission = "0770";
    listenAddr = "0.0.0.0:8080";

    extraRecords = [
      {
        name = "vaultwarden.i.772551232.xyz";
        type = "A";
        value = "192.168.0.2";
      }
    ];
  };
}
