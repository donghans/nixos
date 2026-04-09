{lib, ...}:
with lib; {
  options = {
    workspace = {
      username = mkOption {
        type = types.str;
        description = "Main user username";
      };
      gitName = mkOption {
        type = types.str;
        description = "Git user name";
      };
      gitEmail = mkOption {
        type = types.str;
        description = "Git user email";
      };
      nixosRepo = mkOption {
        type = types.str;
        description = "NixOS repository path or URL";
      };
      hostname = mkOption {
        type = types.str;
        description = "System hostname";
      };
      type = mkOption {
        type = types.enum ["desktop" "laptop" "server" "rpi"];
        description = "Device type: desktop, laptop, server, rpi";
      };
      ramGb = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "RAM size in GB";
      };
      stateVersion = mkOption {
        type = types.str;
        description = "NixOS/Home-Manager state version";
      };
    };
  };
}
