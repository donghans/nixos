{pkgs, ...}: let
  # 🚀 nfd-fix custom script definition
  nfd-fix = pkgs.writeShellScriptBin "nfd-fix" ''
    TARGET=''${1:-.}
    if [[ ! -d "$TARGET" ]]; then
      echo "Error: '$TARGET' is not a valid directory."
      exit 1
    fi

    echo "Searching for NFD filenames in '$TARGET' and converting to NFC..."
    echo "--- [Preview] ---"
    ${pkgs.convmv}/bin/convmv -f utf-8 -t utf-8 --nfc -r "$TARGET"
    echo "-----------------"
    echo -n "Do you want to convert the above files? (y/N): "
    read -r answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      ${pkgs.convmv}/bin/convmv -f utf-8 -t utf-8 --nfc -r --notest "$TARGET"
      echo "Conversion completed."
    else
      echo "Operation cancelled."
    fi
  '';
in {
  environment.systemPackages = [ nfd-fix ];

  # == Zsh Interactive Shell Init ==
  programs.zsh.interactiveShellInit = ''
    # == NFD (Normalization Form Decomposition) file identification helper ==
    nfd-ls() {
      local dir=''${1:-.}
      if [[ ! -d "$dir" ]]; then
        echo "Error: '$dir' is not a valid directory."
        return 1
      fi

      echo "Searching for NFD files in '$dir'..."

      # Using absolute paths to avoid alias conflicts (e.g., tr, grep)
      ${pkgs.convmv}/bin/convmv -f utf-8 -t utf-8 --nfc -r "$dir" 2>&1 | \
      ${pkgs.gnugrep}/bin/grep -E "would rename|mv " | while read -r line; do
        # Extract filename between quotes safely
        local file=$(echo "$line" | ${pkgs.gnugrep}/bin/grep -oE '"[^"]+"' | ${pkgs.coreutils}/bin/head -n 1 | ${pkgs.coreutils}/bin/tr -d '"')
        if [[ -n "$file" ]]; then
          echo -e "\e[31m[NFD Detected]\e[0m $file"
        fi
      done
    }

    # == Key Bindings (Fix Ctrl+Arrow keys word-wise movement) ==
    bindkey "^[[1;5C" forward-word
    bindkey "^[[1;5D" backward-word
    bindkey "^[[1;3C" forward-word
    bindkey "^[[1;3D" backward-word
  '';
}
