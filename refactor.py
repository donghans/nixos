import os
import shutil
import re

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def read_file(path):
    with open(path, 'r') as f:
        return f.read()

# Make target dirs
os.makedirs('mods/gui/apps', exist_ok=True)
os.makedirs('mods/gui/utils', exist_ok=True)
os.makedirs('mods/gui/core', exist_ok=True)
os.makedirs('mods/devel/apps', exist_ok=True)
os.makedirs('mods/devel/toolchains', exist_ok=True)
os.makedirs('mods/devel/jetbrains', exist_ok=True)
os.makedirs('mods/_data/devbox', exist_ok=True)

# 1. GUI Apps
vivaldi_content = read_file('mods/gui/base/home/vivaldi.nix')
vivaldi_inner = re.search(r'home\.packages = \[(.*?)\];', vivaldi_content, re.DOTALL).group(1)
write_file('mods/gui/apps/vivaldi.nix', f'''{{ config, lib, pkgs, unstable, ... }}:
with lib;
let cfg = config.mods.gui.apps.vivaldi;
in {{
  config = mkIf cfg.enable {{
    home.packages = [{vivaldi_inner}];
  }};
}}''')
os.remove('mods/gui/base/home/vivaldi.nix')

write_file('mods/gui/apps/slack.nix', '''{ config, lib, pkgs, unstable, ... }:
with lib;
let cfg = config.mods.gui.apps.slack;
in {
  config = mkIf cfg.enable {
    home.packages = [ unstable.slack ];
    xdg.mimeApps.defaultApplications = {
      "x-scheme-handler/slack" = ["slack.desktop"];
    };
  };
}''')

write_file('mods/gui/apps/bitwarden.nix', '''{ config, lib, pkgs, ... }:
with lib;
let cfg = config.mods.gui.apps.bitwarden;
in {
  config = mkIf cfg.enable {
    home.packages = with pkgs; [ bitwarden-desktop bitwarden-cli ];
  };
}''')

# 2. GUI Utils
write_file('mods/gui/utils/notifications_logger.nix', f'''{{ config, lib, pkgs, ... }}:
with lib;
let cfg = config.mods.gui.utils.notifications_logger;
in {{
  imports = [ ./custom-notify-logger-module.nix ];
  config = mkIf cfg.enable {{
    services.custom-notify-logger.enable = true;
  }};
}}''')
shutil.move('mods/gui/base/os/custom-notify-logger.nix', 'mods/gui/utils/custom-notify-logger-module.nix')
shutil.rmtree('mods/gui/base/os', ignore_errors=True)

# 3. Devel Apps
write_file('mods/devel/apps/llm-cli.nix', '''{ config, lib, pkgs, unstable, unstable-fallback, ... }:
with lib;
let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.llm-cli;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    home.packages = [ unstable-fallback.claude-code unstable.gemini-cli ];
  };
}''')

write_file('mods/devel/apps/zed.nix', '''{ config, lib, pkgs, unstable, ... }:
with lib;
let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.zed;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    home.packages = [ unstable.zed-editor ];
  };
}''')

# Remove old packages from devel/base/home.nix
devel_home = read_file('mods/devel/base/home.nix')
devel_home = re.sub(r'# == Common Development Packages ==.*?\}\;', '', devel_home, flags=re.DOTALL)
devel_home = re.sub(r'xdg\.mimeApps.*?\}\;', '', devel_home, flags=re.DOTALL)
write_file('mods/devel/base/home.nix', devel_home)

# 4. Devel Jetbrains
write_file('mods/devel/jetbrains/android-studio.nix', '''{ config, lib, pkgs, ... }:
with lib;
let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.jetbrains.android-studio;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    programs.adb.enable = true;
    networking.firewall.allowedUDPPorts = [5353];
    users.users.${config.workspace.username}.extraGroups = ["adbusers"];
  };
}''')

devel_os = read_file('mods/devel/base/os.nix')
devel_os = re.sub(r'# == System Services ==.*?extraGroups = \["adbusers"\];\s*\}\;', '', devel_os, flags=re.DOTALL)
write_file('mods/devel/base/os.nix', devel_os)

# 5. Move JSON Data
if os.path.exists('mods/devel/base/home/devbox'):
    shutil.move('mods/devel/base/home/devbox', 'mods/_data/devbox')

# 6. Devel Toolchains & Default
devbox_nix = read_file('mods/devel/base/home/devbox.nix')
devbox_nix = re.sub(r'\./devbox/(.*?\.json)', r'../../../_data/devbox/\1', devbox_nix)
write_file('mods/devel/base/home/devbox.nix', devbox_nix)

wrap_toolchain_template = '''{ config, lib, pkgs, ... }@args:
with lib;
let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.__OPT_NAME__;
in {
  config = mkIf (cfg.enable || modCfg.enable) (import ./__FILE_NAME__-module.nix args);
}'''

for f, opt in [('node.nix', 'node'), ('python.nix', 'python'), ('fvm.nix', 'fvm'), ('devbox.nix', 'devbox'), ('jetbrains.nix', 'jetbrains')]:
    shutil.move(f'mods/devel/base/home/{f}', f'mods/devel/toolchains/{f}-module.nix' if f != 'jetbrains.nix' else f'mods/devel/jetbrains/{f}-module.nix')
    
    wrapper = wrap_toolchain_template.replace('__OPT_NAME__', opt).replace('__FILE_NAME__', f.replace('.nix', ''))
    
    if f == 'jetbrains.nix':
        write_file('mods/devel/jetbrains/default.nix', wrapper)
    else:
        write_file(f'mods/devel/toolchains/{f}', wrapper)

write_file('mods/devel/default.nix', '''{ isNixOS ? false, ... }: {
  imports = [
    ./toolchains/node.nix
    ./toolchains/python.nix
    ./toolchains/fvm.nix
    ./toolchains/devbox.nix
    ./apps/llm-cli.nix
    ./apps/zed.nix
    ./jetbrains/default.nix
    ./jetbrains/android-studio.nix
  ] ++ (if isNixOS then [ ./base/os.nix ] else [])
    ++ (if !isNixOS then [ ./base/home.nix ] else []);
}''')
if os.path.exists('mods/devel/base/default.nix'): os.remove('mods/devel/base/default.nix')

# 7. GUI Core & Default
for f in os.listdir('mods/gui/base'):
    shutil.move(os.path.join('mods/gui/base', f), os.path.join('mods/gui/core', f))
os.rmdir('mods/gui/base')

gui_os = read_file('mods/gui/core/os.nix')
gui_os = gui_os.replace('./os/custom-notify-logger.nix', '')
gui_os = gui_os.replace('../../sys/base/default.nix', '')
write_file('mods/gui/core/os-module.nix', gui_os)
os.remove('mods/gui/core/os.nix')
write_file('mods/gui/core/os.nix', '''{ config, lib, pkgs, ... }@args:
with lib;
let cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (import ./os-module.nix args);
}''')

gui_home = read_file('mods/gui/core/home.nix')
gui_home = gui_home.replace('./home/vivaldi.nix', '')
gui_home = gui_home.replace('../../sys/base/home.nix', '')
write_file('mods/gui/core/home-module.nix', gui_home)
os.remove('mods/gui/core/home.nix')
write_file('mods/gui/core/home.nix', '''{ config, lib, pkgs, ... }@args:
with lib;
let cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (import ./home-module.nix args);
}''')

write_file('mods/gui/default.nix', '''{ isNixOS ? false, ... }: {
  imports = [
    ./apps/vivaldi.nix
    ./apps/slack.nix
    ./apps/bitwarden.nix
    ./utils/notifications_logger.nix
  ] ++ (if isNixOS then [ ./core/os.nix ] else [])
    ++ (if !isNixOS then [ ./core/home.nix ] else []);

  config = {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}''')

# 8. Host Opt-in Migration
def update_host_imports(filepath, mode):
    content = read_file(filepath)
    content = re.sub(r'\.\./\.\./mods/.*\.nix', '', content)
    content = re.sub(r'imports\s*=\s*\[\s*\];', '', content)
    content = re.sub(r'imports\s*=\s*\[\s*([^\]]*?)\s*\];', lambda m: 'imports = [\n' + '\n'.join([l for l in m.group(1).split('\\n') if l.strip()]) + '\n  ];', content)
    
    opt_ins = """
  config = {
    mods.sys.base.enable = true;
    mods.gui.enable = true;
    mods.gui.apps.vivaldi.enable = true;
    mods.gui.apps.slack.enable = true;
    mods.gui.apps.bitwarden.enable = true;
    mods.gui.utils.notifications_logger.enable = true;
    mods.devel.enable = true;
    mods.devel.jetbrains.android-studio.enable = true;
  };"""
    if 'config =' not in content:
        content = re.sub(r'\}\s*$', opt_ins + '\n}', content)
    write_file(filepath, content)

update_host_imports('hosts/msi-summit-me/configuration.nix', 'os')
update_host_imports('hosts/msi-summit-me/home.nix', 'home')
update_host_imports('hosts/beelink-ser7-co/configuration.nix', 'os')
update_host_imports('hosts/beelink-ser7-co/home.nix', 'home')

iso_os = read_file('core/iso.nix')
iso_os = iso_os.replace('./mods/gui/base/os.nix', '')
if 'mods.gui.enable' not in iso_os:
    iso_os = re.sub(r'\}\s*$', '\n  config = { mods.sys.base.enable = true; mods.gui.enable = true; mods.gui.apps.vivaldi.enable = true; };\n}', iso_os)
write_file('core/iso.nix', iso_os)

iso_home = read_file('core/iso.home.nix')
iso_home = iso_home.replace('./mods/gui/base/home.nix', '')
if 'mods.gui.enable' not in iso_home:
    iso_home = re.sub(r'\}\s*$', '\n  config = { mods.sys.base.enable = true; mods.gui.enable = true; mods.gui.apps.vivaldi.enable = true; };\n}', iso_home)
write_file('core/iso.home.nix', iso_home)

flake = read_file('core/flake.nix')
flake = flake.replace('(import ./mods/sys/base/home.nix)', '(import ./mods/sys/default.nix)')
write_file('core/flake.nix', flake)

write_file('mods/default.nix', '''{ isNixOS ? false, ... }: {
  imports = [
    ./sys/default.nix
    ./gui/default.nix
    ./devel/default.nix
  ];
}''')

print("Refactoring applied successfully.")
