# 🏛️ Directory Structure (Final Target)

```text
/home/donghans/nixos/
├── core/           # Engine: Flake, Builders, Scripts (nhw), Libs (mkWrapper)
├── mods/           # Parts: The Mods (sys, gui, devel)
│   ├── _preset/    # Recipes: Pre-assembled sets (workstation, server, etc.)
│   └── _data/      # Assets: Config JSONs (devbox, fvm 등), Static scripts
└── hosts/          # Specs: _info.json, Host configs (_hardware.nix)
```
