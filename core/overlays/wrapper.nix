_self: super: {
  mkWrapper = {
    pkg,
    name ? "${pkg.name}-wrapped",
    binName ? "*",
    libs ? [],
    env ? {},
    addFlags ? [],
    run ? null,
    bins ? [],
  }:
    super.symlinkJoin {
      inherit name;
      paths = [pkg];
      nativeBuildInputs = [super.makeWrapper];
      postBuild = let
        ldPath = super.lib.makeLibraryPath libs;

        argsList =
          (super.lib.optionals (libs != []) [
            ''--set NIX_LD_LIBRARY_PATH "${ldPath}"''
            ''--set NIX_LD "${super.stdenv.cc.bintools.dynamicLinker}"''
          ])
          ++ (super.lib.optionals (bins != []) [
            ''--prefix PATH : "${super.lib.makeBinPath bins}"''
          ])
          ++ (super.lib.mapAttrsToList (k: v: "--set ${k} ${super.lib.escapeShellArg v}") env)
          ++ (super.lib.optionals (run != null) [
            "--run ${super.lib.escapeShellArg run}"
          ])
          ++ (super.lib.optionals (addFlags != []) [
            "--add-flags ${super.lib.escapeShellArg (super.lib.concatStringsSep " " (map super.lib.escapeShellArg addFlags))}"
          ]);

        bashArgs = super.lib.concatStringsSep " \\\n  " argsList;
      in ''
        ${super.lib.optionalString (builtins.length argsList > 0) ''
          if [ "${binName}" = "*" ]; then
            for bin in $out/bin/*; do
              if [ -f "$bin" ]; then
                wrapProgram "$bin" \
                  ${bashArgs}
              fi
            done
          else
            wrapProgram "$out/bin/${binName}" \
              ${bashArgs}
          fi
        ''}
      '';
    };
}
