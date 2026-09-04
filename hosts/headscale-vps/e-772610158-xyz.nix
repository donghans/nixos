{...}: {
  imports = [
    ../_lib/headscale.nix
  ];

  headscale = {
    baseDomain = "i.772610158.xyz";
    enableDerp = true;
    derpRegionId = 900;
    derpRegionCode = "kr-vps";
    derpRegionName = "Korea (VPS)";
    extraRecords = [
      {
        name = "opnsense.i.772610158.xyz";
        type = "A";
        value = "192.168.1.1";
      }
      {
        name = "headscale.i.772610158.xyz";
        type = "A";
        value = "192.168.1.2";
      }
      {
        name = "vaultwarden.i.772610158.xyz";
        type = "A";
        value = "192.168.1.3";
      }
      {
        name = "proxmox.i.772610158.xyz";
        type = "A";
        value = "192.168.1.222";
      }
      {
        name = "veve.i.772610158.xyz";
        type = "A";
        value = "192.168.1.12";
      }
    ];
    oidc = {
      only_start_if_oidc_is_available = true;
      issuer = "https://accounts.google.com";
      client_id = "170530185854-nelsine6eg1casd7hl669taueriv16q6.apps.googleusercontent.com";
      client_secret_path = "/var/lib/nix-secrets/headscale/oidc_client_secret";
      scope = ["openid" "profile" "email"];
      email_verified_required = true;
      extra_params.prompt = "select_account";
      allowed_domains = ["bitstep.it"];
      user_scope_strip_domain = true;
      pkce = {
        enabled = true;
        method = "S256";
      };
    };
  };

  users.users.admin.extraGroups = ["headscale"];
}
