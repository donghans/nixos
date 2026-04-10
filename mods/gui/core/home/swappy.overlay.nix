final: prev: {
  # (목적: nixpkgs swappy wrapper가 wl-clipboard를 PATH에 포함하지 않아 복사 버튼 실패)
  swappy = prev.swappy.overrideAttrs (old: {
    postFixup = (old.postFixup or "") + ''
      wrapProgram $out/bin/swappy \
        --prefix PATH : ${prev.lib.makeBinPath [prev.wl-clipboard]}
    '';
  });
}
