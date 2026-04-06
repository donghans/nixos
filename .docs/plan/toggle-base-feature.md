# Base Feature Toggle Architecture Plan

## Background & Motivation
The foundational layer (`lib/_base/`) currently bundles core system utilities, UI components, and background services together. To support more flexible baseline configurations (e.g., a lightweight headless server vs. a full desktop), we need to introduce logical feature toggles using `lib.mkEnableOption` and `lib.mkOption`.

Instead of making changes immediately, this document serves as a blueprint for future implementation. The developer environments (`lib/developer.home/`) will remain untoggled and managed per-file as they are now.

## Namespace & Architecture
We will use a unified `my.*` namespace strictly within the `_base` modules. All features remain enabled by default or depend dynamically on other toggles, ensuring existing hosts (`msi-summit-me`, `beelink-ser7-co`) continue to function without modification.

### 1. Dynamic Dependency: Fonts & TTY
- **`my.sys.kmscon.enable`**: Toggles the hardware-accelerated KMSCon terminal. (Default: `true`)
- **`my.sys.cjkFonts.enable`**: Toggles heavy CJK fonts (Noto, Nanum).
  - **Dynamic Default:** `config.my.sys.kmscon.enable || config.my.sys.hyprland.enable`
  - *Result:* If a user explicitly disables both KMSCon and Hyprland (e.g., a pure headless server), CJK fonts will automatically turn off to save space.

### 2. Desktop Environment: Hyprland & Sub-components
The graphical session will be governed by a master toggle, with sub-toggles for specific UI components.
- **`my.sys.hyprland.enable`**: Master toggle for the Hyprland session and its core services (polkit, portal). (Default: `true`)
- **Sub-components (Nested under Hyprland)**: These default to `config.my.sys.hyprland.enable`, meaning they follow the master toggle's state but can be manually overridden if Hyprland is active.
  - `my.sys.hyprland.waybar.enable`: Top status bar.
  - `my.sys.hyprland.fuzzel.enable`: Application launcher.
  - `my.sys.hyprland.mako.enable`: Notification daemon.
  - `my.sys.hyprland.hyprlock.enable`: Screen locker.

### 3. File Management (`my.desktop.fileManager.enable`)
Coordinates file management tools across system and user boundaries. (Default: `true`)
- **System (`default.nix`)**: `services.gvfs.enable`, `services.udisks2.enable`.
- **User (`default.home.nix`)**: `services.udiskie.enable`, `trash-cli` package, and trash-related shell aliases.
- **UI (`hyprland.home.nix`)**: `nemo` package.

### 4. Desktop Utilities (`my.desktop.*`)
Located in `hyprland.home.nix` (only applicable if Hyprland is enabled):
- `my.desktop.cliphist.enable`: Clipboard history (`cliphist`, `wl-clip-persist`). (Default: `true`)
- `my.desktop.gh.enable`: GitHub CLI integration (`gh`). (Default: `true`)

## Implementation Guide (Future Reference)

### 1. Option Declaration Examples
**Dynamic Default Example (CJK Fonts in `default.nix`)**
```nix
options.my.sys.cjkFonts.enable = lib.mkOption {
  type = lib.types.bool;
  # Dynamically defaults to true if KMSCon OR Hyprland is enabled
  default = config.my.sys.kmscon.enable || config.my.sys.hyprland.enable; 
};

config = lib.mkIf config.my.sys.cjkFonts.enable {
  fonts = {
    packages = with pkgs; [ nanum noto-fonts-cjk-sans ... ];
  };
};
```

**Nested UI Toggles Example (`hyprland.home.nix`)**
```nix
options.my.sys.hyprland = {
  enable = lib.mkOption { type = lib.types.bool; default = true; };
  waybar.enable = lib.mkOption { type = lib.types.bool; default = config.my.sys.hyprland.enable; };
  fuzzel.enable = lib.mkOption { type = lib.types.bool; default = config.my.sys.hyprland.enable; };
};

config = lib.mkMerge [
  (lib.mkIf config.my.sys.hyprland.enable {
    wayland.windowManager.hyprland.enable = true;
  })
  
  (lib.mkIf config.my.sys.hyprland.waybar.enable {
    # Include waybar configs here
  })
];
```

### 2. Example Host Configuration Override
When this architecture is implemented, a user building a minimal desktop can override these defaults in their host configuration:

```nix
# dev/minimal-desktop/configuration.nix
{ ... }: {
  imports = [ ../../lib/_base/default.nix ];

  # Keep Hyprland, but swap Waybar for a custom bar, and remove Fuzzel
  my.sys.hyprland.waybar.enable = false;
  my.sys.hyprland.fuzzel.enable = false;
  
  # CJK Fonts remain enabled automatically because Hyprland is true.
  
  # Opt-out of file management tools
  my.desktop.fileManager.enable = false;
}
```

## Verification Strategy
When implemented, execute `nhw check` to ensure valid syntax. An initial deployment (`nhw os switch`) with no toggles modified should result in zero changes to the built output, proving backward compatibility. Test the dynamic dependency by disabling KMSCon and Hyprland on a test host, verifying that `nanum` and `noto-fonts-cjk` are successfully removed from the system closure.
