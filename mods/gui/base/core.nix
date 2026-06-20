{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  config,
  options,
  pkgs,
  lib,
  ...
}: {
  os = lib.mkIf config.mods.gui.enable {
    # (목적: Wayland/GPU 가속을 위한 그래픽 드라이버 활성화)
    hardware.graphics.enable = true;
    hardware.graphics.enable32Bit = pkgs.stdenv.hostPlatform.isx86_64;

    programs = {
      uwsm.enable = true;
      hyprland.enable = true;
      hyprland.withUWSM = true;
    };

    # greeter.nix에 uwsm 세션 커맨드 주입
    mods.gui.base.greeter.sessionCmd = "uwsm start hyprland-uwsm.desktop";

    # (참고: services.blueman.enable은 mods.sys.services.bluetooth.nix에서 조건부 처리)
  };
  hm = lib.mkMerge [
    {
      _module.args = {
        hyprTerm = "${pkgs.kitty}/bin/kitty";
      };
    }
    (lib.mkIf config.mods.gui.enable {
      wayland.windowManager.hyprland =
        {
          enable = true;
          package = pkgs.hyprland;
          systemd = {
            enable = false;
            variables = ["--all"];
          };
        }
        // (lib.optionalAttrs (options.wayland.windowManager.hyprland ? configType) {
          configType = "lua";
        });

      xdg.configFile."hypr/hyprland.lua".source = let
        cfg = config.wayland.windowManager.hyprland;
        toLua = lib.generators.toLua {};

        pluginPath = entry:
          if lib.types.package.check entry
          then "${entry}/lib/lib${entry.pname}.so"
          else entry;

        variables = builtins.concatStringsSep " " cfg.systemd.variables;
        extraCommands = builtins.concatStringsSep " " (map (f: "&& ${f}") cfg.systemd.extraCommands);
        systemdActivationCommand = "${pkgs.dbus}/bin/dbus-update-activation-environment --systemd ${variables} ${extraCommands}";

        cleanSettings = builtins.removeAttrs cfg.settings ["exec-once"];

        pluginLoadCommands = map (entry: "hyprctl plugin load ${pluginPath entry}") cfg.plugins;

        userStartupCommands = let
          execOnce = cfg.settings."exec-once" or [];
        in
          if builtins.isList execOnce
          then execOnce
          else [execOnce];

        startupCommands =
          lib.optionals cfg.systemd.enable [systemdActivationCommand]
          ++ pluginLoadCommands
          ++ userStartupCommands;

        renderArgs = value:
          if lib.isAttrs value && value ? _args
          then lib.concatMapStringsSep ", " toLua value._args
          else toLua value;

        renderSection = name: text:
          lib.optionalString (text != "") ''
            -- ${name}
            ${text}
          '';

        parseMonitor = str: let
          parts = lib.splitString "," str;
          len = builtins.length parts;
          trim = lib.strings.trim;
          trimmed = map trim parts;
        in
          if len >= 4
          then {
            output = builtins.elemAt trimmed 0;
            mode = builtins.elemAt trimmed 1;
            position = builtins.elemAt trimmed 2;
            scale = let
              s = builtins.elemAt trimmed 3;
            in
              if s == "auto"
              then "auto"
              else if builtins.match "[0-9.]+" s != null
              then builtins.fromJSON s
              else s;
          }
          else {
            output = str;
          };

        renderLegacyBind = type: legacyBindStr: let
          parts = lib.splitString "," legacyBindStr;
          len = builtins.length parts;
        in
          if len < 3
          then "-- invalid legacy bind: ${legacyBindStr}\n"
          else let
            mod = lib.strings.trim (builtins.elemAt parts 0);
            key = lib.strings.trim (builtins.elemAt parts 1);
            dispatcher = lib.strings.trim (builtins.elemAt parts 2);
            args = lib.strings.trim (builtins.concatStringsSep "," (builtins.tail (builtins.tail (builtins.tail parts))));

            luaKeys =
              if mod == ""
              then key
              else "${mod} + ${key}";
            luaDispatcher =
              if dispatcher == "exec"
              then "hl.dsp.exec_cmd(${toLua args})"
              else "hl.dsp.exec_raw(${toLua "${dispatcher} ${args}"})";

            flags =
              (lib.optionalAttrs (type == "binde" || type == "bindel") {repeating = true;})
              // (lib.optionalAttrs (type == "bindl" || type == "bindel") {locked = true;})
              // (lib.optionalAttrs (type == "bindr") {release = true;});

            luaFlags =
              if flags == {}
              then ""
              else ", ${toLua flags}";
          in "hl.bind(${toLua luaKeys}, ${luaDispatcher}${luaFlags})\n";

        renderSettings = let
          names = lib.sort lib.lessThan (lib.attrNames cleanSettings);
          luaLocalNames =
            builtins.filter (
              name: lib.isAttrs cleanSettings.${name} && cleanSettings.${name} ? _var
            )
            names;
          settingNames = builtins.filter (name: !(builtins.elem name luaLocalNames)) names;

          renderLocal = name: let
            value = cleanSettings.${name};
          in "local ${value.name or name} = ${renderArgs value._var}\n";

          configSections =
            builtins.filter (
              name: let
                val = cleanSettings.${name};
              in
                lib.isAttrs val && !(val ? _var)
            )
            settingNames;

          configAttrs = lib.filterAttrs (name: _: builtins.elem name configSections) cleanSettings;

          renderConfigBlock =
            if configSections == []
            then ""
            else ''
              -- settings.config
              hl.config(${toLua configAttrs})

            '';

          monitorList = cleanSettings.monitor or [];
          renderMonitor = str: "hl.monitor(${toLua (parseMonitor str)})\n";
          renderMonitors =
            if monitorList == []
            then ""
            else ''
              -- settings.monitor
              ${lib.concatMapStrings renderMonitor monitorList}

            '';

          bindTypes = ["bind" "binde" "bindl" "bindel" "bindr"];

          renderBindSection = type: let
            binds = cleanSettings.${type} or [];
          in
            lib.optionalString (binds != []) ''
              -- settings.${type}
              ${lib.concatMapStrings (renderLegacyBind type) binds}
            '';

          renderAllBinds = lib.concatMapStrings renderBindSection bindTypes;

          otherNames =
            builtins.filter (
              name:
                !(builtins.elem name configSections)
                && !(builtins.elem name bindTypes)
                && name != "monitor"
            )
            settingNames;

          renderCall = name: value: "hl.${name}(${renderArgs value})\n";
          renderCalls = name: value:
            lib.concatMapStrings (renderCall name) (
              if builtins.isList value
              then value
              else [value]
            );

          renderOthers =
            lib.concatMapStrings (
              name: renderSection "settings.${name}" (renderCalls name cleanSettings.${name})
            )
            otherNames;
        in
          lib.optionalString (luaLocalNames != []) (
            renderSection "settings.locals" (lib.concatMapStrings renderLocal luaLocalNames)
          )
          + renderConfigBlock
          + renderMonitors
          + renderAllBinds
          + renderOthers;

        renderStartHook =
          if startupCommands == []
          then ""
          else
            renderSection "startup" ''
              hl.on("hyprland.start", function()
              ${lib.concatMapStrings (command: "  hl.exec_cmd(${toLua command})\n") startupCommands}end)
            '';

        renderSubmaps = let
          renderLuaArg = value: lib.replaceStrings ["\n"] ["\n  "] (renderArgs value);
          renderCall = name: value: "  hl.${name}(${renderLuaArg value})\n";
          renderCalls = name: values:
            lib.concatMapStrings (renderCall name) (builtins.filter (value: !lib.isString value) values);
          renderSubmap = name: submap:
            renderSection "submaps.${name}" (
              "hl.define_submap(${toLua name}"
              + lib.optionalString (submap.onDispatch != "") ", ${toLua submap.onDispatch}"
              + ", function()\n"
              + lib.concatMapStrings (settingName: renderCalls settingName submap.settings.${settingName}) (
                lib.sort lib.lessThan (lib.attrNames submap.settings)
              )
              + "end)\n"
            );
          hasLuaSettings = submap:
            lib.any (values: builtins.any (value: !lib.isString value) values) (lib.attrValues submap.settings);
          luaSubmaps = lib.filterAttrs (_: hasLuaSettings) cfg.submaps;
          names = lib.sort lib.lessThan (lib.attrNames luaSubmaps);
        in
          lib.concatMapStrings (name: renderSubmap name luaSubmaps.${name}) names;
      in
        pkgs.writeTextFile {
          name = "hyprland.lua";
          text =
            ''
              -- Generated by Home Manager (patched by nixup config).
              -- See https://wiki.hypr.land/Configuring/Start/

            ''
            + renderSettings
            + renderSubmaps
            + renderStartHook
            + renderSection "extraConfig" cfg.extraConfig;
          checkPhase = ''
            ${pkgs.lua5_4}/bin/luac -p "$out"
          '';
        };

      home.packages = with pkgs; [
        nemo
      ];

      # == Wayland 환경 변수 ==
      home.sessionVariables = {
        ELECTRON_OZONE_PLATFORM_HINT = "auto";
      };

      # (참고: exec-once 위치)
      # - bluetooth        → mods/sys/services/bluetooth.nix
      # - networkmanager   → mods/sys/services/networkmanager.nix
      # - tailscale        → mods/sys/services/tailscale.nix
      # - hyprpaper        → hyprpaper.nix
      # - wl-clip-persist  → wl-clip.nix
      # - hyprpolkitagent  → polkit.nix
      # - fcitx5           → fcitx.nix
      # - waybar           → waybar.nix
    })
  ];
})
