{mkModOf, ...}:
mkModOf "mods.devel" __curPos "Playwright browser testing" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.playwright-wrapped];
    # PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD 의도적으로 미설정:
    # registry.js에서 install 명령까지 막으므로 세션 변수로 주입하면 안 됨.
    # npm install postinstall 또는 playwright install chromium 으로 브라우저를 받고,
    # playwright-wrapped가 NIX_LD_LIBRARY_PATH로 런타임 링킹을 처리한다.
  };
})
