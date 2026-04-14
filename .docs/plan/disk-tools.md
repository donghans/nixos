# Disk Tools Integration Plan (Draft for Later)

> **Task Scope**: The current objective is solely to save this plan to `.docs/plan/disk-tools.md` so it can be implemented later. No system configurations or Nix files will be modified at this time.

## Background & Motivation
The user requested a better way to monitor disk usage and file sizes than the standard `df` and `du` commands. To address this, we will introduce modern CLI alternatives (`duf`, `dust`, `ncdu`) and a set of convenient shell aliases for quick checks. Following the project's modular architecture, this will be encapsulated in a new sys utility module.

## Key Files & Context
- **`mods/sys/utils/disk-tools.nix`** (New File): The Nix module containing the package definitions and aliases.
- **`mods/sys/default.nix`** (Modified File): Will import the new `disk-tools.nix` module.
- **`mods/_preset/workstation.toml`** (Modified File): Will enable the `disk-tools` module for workstation environments.

## Implementation Steps (For Later)

### 1. Create `mods/sys/utils/disk-tools.nix`
Create the file with the following structure to handle both `isNixOS` (system-level) and home-manager environments seamlessly:

```nix
{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.utils.disk-tools;
  
  aliases = {
    dsize = "du -sh * | sort -h";
    dutotal = "du -sh .";
    du1 = "du -h --max-depth=1";
    dtop = "du -ah . | sort -rh | head -n 10";
    dfx = "df -h -x tmpfs -x devtmpfs -x efivarfs";
  };
in {
  options.mods.sys.utils.disk-tools.enable = mkEnableOption "Modern disk monitoring tools (duf, dust, ncdu)";
  
  config = mkIf cfg.enable (
    if isNixOS
    then {
      environment.systemPackages = with pkgs; [ duf du-dust ncdu ];
      environment.shellAliases = aliases;
    }
    else {
      home.packages = with pkgs; [ duf du-dust ncdu ];
      home.shellAliases = aliases;
    }
  );
}
```

### 2. Import the module in `mods/sys/default.nix`
Add `./utils/disk-tools.nix` to the `imports` list in `mods/sys/default.nix`.

```nix
  imports =
    [
      ./fonts.nix
      ./vfs.nix
      ./utils/nfd.nix
      ./utils/disk-tools.nix # <-- 추가
      ./services/bluetooth.nix
      ...
```

### 3. Enable in `mods/_preset/workstation.toml`
Add the module to the workstation preset configuration to make these tools available by default on workstation profiles.

```toml
[mods.sys.utils]
nfd = true
disk-tools = true
```

## Verification & Testing (For Later)
1. Run `nixup check` to validate the syntax, run formatting, and ensure the Flake evaluates successfully for the current host profile.
2. Run `nixup os` to apply the changes to the current host.
3. Test the commands manually in a new shell:
   - Run `duf` and `dust`.
   - Run `dsize` and `dfx` aliases to ensure they work properly.
