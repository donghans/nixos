# mods/_patches — 외부 소스에 적용하는 패치

nixpkgs 패키지에 얹는 `.patch` 를 둔다. 폴더 하나가 패키지 하나다.
- `wofi/` — wofi 1.5.3 소스 패치 8개(`mods/gui/base/wofi.overlay.nix` 가 `patches` 로 적용, `--fuzz=0`). 목록·주의는 `wofi/README.md`.
- `wvkbd/` — wvkbd 패치(`float-mode`·`pc-layout`; `mods/gui/base/vkb.nix` 가 적용). 설명은 `wvkbd/README.md`.
