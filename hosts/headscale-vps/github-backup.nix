{...}: {
  imports = [../_lib/headscale-db-backup.nix];

  services.headscale-db-backup = {
    enable = true;
    appId = "3995077";
    installationId = "138797641";
    privateKeyFile = "/var/lib/nix-secrets/github-apps/private-key.pem";
    repoUrl = "https://github.com/BITSTEP-IT/headscale-backup.git";
  };
}
