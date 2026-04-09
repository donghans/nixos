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
        description = "RAM size in GB (auto-detected from /proc/meminfo if not set in host.toml)";
      };
      swapGb = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "Swap file size in GB. Default: ceil(ramGb * 0.75). Set to 0 to disable swap.";
      };
      tmpfsSize = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "tmpfs /tmp size as percentage of RAM (e.g. \"100%\"). Default: \"100%\".";
      };
      zramPercent = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "ZRAM pool size as percentage of physical RAM. Default: 50.";
      };
      stateVersion = mkOption {
        type = types.str;
        description = "NixOS/Home-Manager state version";
      };
    };
  };
}
