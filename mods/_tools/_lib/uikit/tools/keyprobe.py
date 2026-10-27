import asyncio, os, sys, time, tempfile
R="/home/donghans/nixos/mods/_tools"
for p in ("observe","_lib/uikit","procui","llm-sessions","notif","clipboard","display","../_data/claude-skills/donghans-host-resources/scripts"): sys.path.insert(0, f"{R}/{p}")
which=sys.argv[1]
def make():
    if which=="usageui":
        import usagedata as ud, usageui; return usageui.UsageUI(ud.preset("1시간", time.time()), tab="dashboard")
    if which=="usageui-live":
        import usagedata as ud, usageui; return usageui.UsageUI(ud.preset("1시간", time.time()))
    if which=="procui":
        import procui; return procui.ProcUI(log_path="/tmp/x.jsonl")
    if which=="sessions":
        import llm_sessions as cs; return cs.SessionsUI()
    if which=="notif":
        import notif_ui; return notif_ui.NotifUI()
    if which=="clip":
        import clipui; return clipui.ClipUI()
    if which=="display":
        import displayui; return displayui.DisplayUI()
KEYS=["q","escape","ctrl+c","ctrl+q"]
HELP_CLOSE=["escape","q","question_mark","f1","enter","x","space"]
async def one(key):
    app=make()
    async with app.run_test(size=(140,42)) as pilot:
        await pilot.pause(1.2)
        before=len(app.screen_stack)
        await pilot.press(key); await pilot.pause(0.6)
        notes=[str(n.message)[:40] for n in getattr(app,"_notifications",[])] if hasattr(app,"_notifications") else []
        return dict(exited=bool(getattr(app,"_exit",False)), stack=len(app.screen_stack), notes=notes)
async def helptest(open_key, close_key):
    app=make()
    async with app.run_test(size=(140,42)) as pilot:
        await pilot.pause(1.2)
        await pilot.press(open_key); await pilot.pause(0.5)
        opened = app.screen.__class__.__name__ == "HelpScreen"
        if not opened: return "열리지 않음"
        await pilot.press(close_key); await pilot.pause(0.4)
        return "닫힘" if app.screen.__class__.__name__ != "HelpScreen" else "그대로"
async def main():
    print(f"## {which}")
    for k in KEYS:
        try: print(f"  {k:<8}", await one(k))
        except Exception as e: print(f"  {k:<8} ERR {type(e).__name__}: {str(e)[:80]}")
    for ok in ("question_mark","f1"):
        res={}
        for ck in HELP_CLOSE:
            try: res[ck]=await helptest(ok, ck)
            except Exception as e: res[ck]="ERR"
        print(f"  help open={ok:<14}", res)
asyncio.run(main())
