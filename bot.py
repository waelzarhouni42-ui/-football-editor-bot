import os, asyncio, subprocess, tempfile
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
if not TOKEN: raise RuntimeError("BOT_TOKEN fehlt.")
pending={}

def dur(p):
    r=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",p],capture_output=True,text=True,check=True)
    return float(r.stdout.strip())

def audio(p):
    r=subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_type","-of","default=nw=1:nk=1",p],capture_output=True,text=True)
    return bool(r.stdout.strip())

def esc(s):
    return s.replace("\\","\\\\").replace(":","\\:").replace("'","\\'").replace("%","\\%").replace(",","\\,")

def render(inp,out,secs,style,hook):
    d=dur(inp); secs=max(1,min(int(secs),int(d))); has_a=audio(inp)
    vf=["scale=720:1280:force_original_aspect_ratio=increase","crop=720:1280","setsar=1","fps=30","format=yuv420p"]
    if style in ("hype","meme"):
        vf += ["scale=750:1334","crop=720:1280","setsar=1"]
        h=esc((hook or "WHAT A MOMENT")[:50])
        vf += [f"drawtext=text='{h}':fontcolor=white:fontsize=42:borderw=4:bordercolor=black:x=(w-text_w)/2:y=80:enable='between(t,0,3.5)'"]
    if style=="meme":
        vf += ["drawtext=text='WAIT FOR IT...':fontcolor=white:fontsize=36:borderw=4:bordercolor=black:x=(w-text_w)/2:y=h-120:enable='between(t,3.5,7)'"]
    slow = style=="slow"
    if slow: vf += ["setpts=PTS/0.88"]
    cmd=["ffmpeg","-y","-i",inp,"-t",str(secs),"-vf",",".join(vf)]
    if has_a:
        if slow: cmd += ["-af","atempo=0.88"]
        cmd += ["-c:a","aac","-b:a","128k","-ar","44100"]
    else: cmd += ["-an"]
    cmd += ["-c:v","libx264","-preset","ultrafast","-crf","25","-threads","2","-movflags","+faststart",out]
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode:
        # Stable clean fallback
        base="scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,format=yuv420p"
        cmd=["ffmpeg","-y","-i",inp,"-t",str(secs),"-vf",base,"-c:v","libx264","-preset","ultrafast","-crf","25","-threads","2"]
        if has_a: cmd += ["-c:a","aac","-b:a","128k","-ar","44100"]
        else: cmd += ["-an"]
        cmd += ["-movflags","+faststart",out]
        p=subprocess.run(cmd,capture_output=True,text=True)
        if p.returncode: raise RuntimeError(p.stderr[-2000:])
    return secs

async def start(u,c):
    await u.message.reply_text("⚽ Football Editor Bot\n\nSchick mir ein Fußballvideo.\nOptional: Hook als Caption zum Video.\n\nNutze nur Material, das du verwenden darfst.")

async def recv(u,c):
    m=u.message.video or u.message.document
    if not m:return
    pending[u.effective_chat.id]={"id":m.file_id,"hook":u.message.caption or "WHAT A MOMENT"}
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("30 Sek.",callback_data="l30"),InlineKeyboardButton("60 Sek.",callback_data="l60")],[InlineKeyboardButton("90 Sek.",callback_data="l90"),InlineKeyboardButton("Maximal",callback_data="lmax")]])
    await u.message.reply_text("1/2 Welche Länge?",reply_markup=kb)

async def length(u,c):
    q=u.callback_query; await q.answer(); x=pending.get(u.effective_chat.id)
    if not x: return await q.edit_message_text("Video bitte nochmal schicken.")
    x["len"]=q.data[1:]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔥 Hype",callback_data="shype"),InlineKeyboardButton("😂 Meme",callback_data="smeme")],[InlineKeyboardButton("🐢 Slow Motion",callback_data="sslow"),InlineKeyboardButton("⚡ Clean",callback_data="sclean")]])
    await q.edit_message_text("2/2 Welcher Stil?",reply_markup=kb)

async def style(u,c):
    q=u.callback_query; await q.answer(); x=pending.get(u.effective_chat.id)
    if not x:return
    s=q.data[1:]; await q.edit_message_text("⏳ Edit wird erstellt ...")
    try:
        f=await c.bot.get_file(x["id"])
        with tempfile.TemporaryDirectory() as td:
            inp=str(Path(td)/"in.mp4"); out=str(Path(td)/"edit.mp4")
            await f.download_to_drive(inp)
            d=dur(inp); n=int(d) if x["len"]=="max" else int(x["len"]); n=min(n,int(d),120)
            loop=asyncio.get_running_loop()
            made=await loop.run_in_executor(None,render,inp,out,n,s,x["hook"])
            names={"hype":"🔥 Hype","meme":"😂 Meme","slow":"🐢 Slow Motion","clean":"⚡ Clean"}
            with open(out,"rb") as v: await q.message.reply_video(video=v,supports_streaming=True,caption=f"✅ Fertig – {made} Sek. | {names[s]}")
        pending.pop(u.effective_chat.id,None)
    except Exception as e:
        print("EDIT ERROR",repr(e),flush=True)
        await q.message.reply_text("❌ Bearbeitung fehlgeschlagen.\n"+str(e)[-1500:])

def main():
    app=Application.builder().token(TOKEN).read_timeout(300).write_timeout(300).connect_timeout(60).pool_timeout(60).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.VIDEO|filters.Document.VIDEO,recv))
    app.add_handler(CallbackQueryHandler(length,pattern=r"^l"))
    app.add_handler(CallbackQueryHandler(style,pattern=r"^s"))
    print("BOT READY",flush=True); app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
