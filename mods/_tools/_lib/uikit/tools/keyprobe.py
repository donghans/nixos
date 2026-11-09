import asyncio, os, sys, time, tempfile
R="/home/donghans/nixos/mods/_tools"
for p in ("observe/observe","_lib/uikit","observe/process-manager","llm/llm-sessions","desktop/notification-center","desktop/clipboard","desktop/embedctl","desktop/monitor-manager","llm/llm-ctx","../_data/claude-skills/donghans-host-resources/scripts"): sys.path.insert(0, f"{R}/{p}")
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
    if which=="embedctlui":
        import embedctlui; return embedctlui.EmbedUI()
KEYS=["q","escape","ctrl+c","ctrl+q"]
HELP_CLOSE=["escape","question_mark","f1","enter","q","x","space"]        # q·x·space 는 닫히면 안 된다(2026-11-03 q 제거)
async def one(key):
    app=make()
    async with app.run_test(size=(140,42)) as pilot:
        await pilot.pause(1.2)
        before=len(app.screen_stack)
        await pilot.press(key); await pilot.pause(0.6)
        notes=[str(n.message)[:40] for n in getattr(app,"_notifications",[])] if hasattr(app,"_notifications") else []
        res=dict(exited=bool(getattr(app,"_exit",False)), stack=len(app.screen_stack), notes=notes)
        if key=="escape" and res["stack"]>1:      # 종료 확인창이 떴으면 Enter(기본 아니오=취소) 와 y(종료) 도 확인
            top=type(app.screen).__name__
            await pilot.press("enter"); await pilot.pause(0.4)
            res["confirm"]=f"{top}; Enter→{'종료' if getattr(app,'_exit',False) else '취소'}"
            if not getattr(app,"_exit",False):
                await pilot.press("escape"); await pilot.pause(0.4); await pilot.press("right"); await pilot.pause(0.2); await pilot.press("enter"); await pilot.pause(0.4)
                res["confirm"]+=f"; Esc→→→Enter→{'종료' if getattr(app,'_exit',False) else '안 꺼짐'}"
        return res
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
