{...}: {
  virtualisation.docker.enable = true;
  users.users.admin.extraGroups = ["docker"];

  systemd.tmpfiles.rules = [
    "d /home/admin/landings 0755 admin users -"
  ];
}
