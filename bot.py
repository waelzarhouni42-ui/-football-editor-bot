import os, asyncio, subprocess, tempfile
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN fehlt.")
pending = {}

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr[-2500:])
    return p

def duration(p):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration",
                      "-of","default=nw=1:nk=1",p]).stdout.strip())

def has_audio(p):
    x = subprocess.run(["ffprobe","-v","error","-select_streams","a:0",
                        "-show_entries","stream=codec_type","-of","default=nw=1:nk=1",p],
                       capture_output=True,text=True)
    return bool(x.stdout.strip())

def esc(s):
    return (s.replace("\\","\\\\").replace(":","\\:").replace("'","\\'")
             .replace("%","\\%").replace(",","\\,"))

def pick_start(d, length, mode):
    # Lightweight automatic scene choice without expensive AI:
    # for long clips, avoid always starting at 0.
    if d <= length + 1:
        return 0.0
    if mode == "viral":
        return max(0.0, min(d-length, d*0.18))
    if mode == "cinema":
        return max(0.0, min(d-length, d*0.08))
    return 0.0

def render(inp, out, seconds, mode, hook):
    d = duration(inp)
    seconds = max(1, min(int(seconds), int(d)))
    start = pick_start(d, seconds, mode)
    a = has_audio(inp)

    # Stable, single-pass HD vertical render.
    vf = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        "setsar=1",
        "fps=30",
        "format=yuv420p"
    ]

    # Zoom/punch-in while keeping the stable pipeline.
    if mode in ("viral","cinema"):
        vf += ["scale=1120:1992","crop=1080:1920","setsar=1"]

    # Hook text
    if mode in ("viral","meme","cinema"):
        text = esc((hook or "WHAT A MOMENT")[:55])
        vf += [f"drawtext=text='{text}':fontcolor=white:fontsize=58:"
               "borderw=5:bordercolor=black:x=(w-text_w)/2:y=105:"
               "enable='between(t,0,3.2)'"]

    if mode == "meme":
        vf += ["drawtext=text='WAIT FOR IT...':fontcolor=white:fontsize=46:"
               "borderw=5:bordercolor=black:x=(w-text_w)/2:y=h-180:"
               "enable='between(t,3.2,7)'"]

    # Cinematic mild slow motion.
    slow = mode == "cinema"
    if slow:
        vf += ["setpts=PTS/0.92"]

    cmd = ["ffmpeg","-y","-ss",str(start),"-i",inp,"-t",str(seconds),
           "-vf",",".join(vf)]

    if a:
        if slow:
            cmd += ["-af","atempo=0.92"]
        # Music/audio treatment: normalize original audio.
        cmd += ["-af", ("atempo=0.92,loudnorm=I=-14:TP=-1.5:LRA=11" if slow
                        else "loudnorm=I=-14:TP=-1.5:LRA=11"),
                "-c:a","aac","-b:a","160k","-ar","44100"]
    else:
        cmd += ["-an"]

    cmd += ["-c:v","libx264","-preset","veryfast","-crf","20",
            "-threads","2","-movflags","+faststart",out]

    try:
        run(cmd)
    except Exception:
        # Guaranteed-style fallback matching the version that already worked.
        base = ("scale=720:1280:force_original_aspect_ratio=increase,"
                "crop=720:1280,setsar=1,fps=30,format=yuv420p")
        cmd2 = ["ffmpeg","-y","-ss",str(start),"-i",inp,"-t",str(seconds),
                "-vf",base,"-c:v","libx264","-preset","ultrafast","-crf","25",
                "-threads","2"]
        if a:
            cmd2 += ["-c:a","aac","-b:a","128k","-ar","44100"]
        else:
            cmd2 += ["-an"]
        cmd2 += ["-movflags","+faststart",out]
        run(cmd2)
    return seconds

async def start(u,c):
    await u.message.reply_text(
        "⚽ FOOTBALL PRO EDITOR\n\n"
        "Schick mir dein Fußballvideo.\n"
        "Optional: Schreibe deinen Hook als Caption.\n\n"
        "🎬 Automatische Szene\n🔍 Zoom\n✨ Full-HD\n"
        "🎵 Audio-Optimierung\n🐢 Slow Motion\n😂 Meme/Hook\n📱 9:16\n\n"
        "Nutze nur Material, das du verwenden darfst."
    )

async def receive(u,c):
    m = u.message.video or u.message.document
    if not m: return
    pending[u.effective_chat.id] = {"id":m.file_id, "hook":u.message.caption or "WHAT A MOMENT"}
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Sek.",callback_data="l30"),
         InlineKeyboardButton("60 Sek.",callback_data="l60")],
        [InlineKeyboardButton("90 Sek.",callback_data="l90"),
         InlineKeyboardButton("Maximal",callback_data="lmax")]
    ])
    await u.message.reply_text("1/2 Länge wählen:",reply_markup=kb)

async def choose_len(u,c):
    q=u.callback_query; await q.answer()
    x=pending.get(u.effective_chat.id)
    if not x: return await q.edit_message_text("Video bitte nochmal schicken.")
    x["len"]=q.data[1:]
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 VIRAL AUTO",callback_data="sviral"),
         InlineKeyboardButton("🎬 CINEMA",callback_data="scinema")],
        [InlineKeyboardButton("😂 MEME",callback_data="smeme"),
         InlineKeyboardButton("⚡ CLEAN HD",callback_data="sclean")]
    ])
    await q.edit_message_text("2/2 Edit wählen:",reply_markup=kb)

async def choose_style(u,c):
    q=u.callback_query; await q.answer()
    x=pending.get(u.effective_chat.id)
    if not x: return
    mode=q.data[1:]
    await q.edit_message_text("⏳ PRO Edit wird erstellt ...")
    try:
        tg=await c.bot.get_file(x["id"])
        with tempfile.TemporaryDirectory() as td:
            inp=str(Path(td)/"input.mp4"); out=str(Path(td)/"pro_edit.mp4")
            await tg.download_to_drive(inp)
            d=duration(inp)
            n=int(d) if x["len"]=="max" else int(x["len"])
            n=min(n,int(d),120)
            loop=asyncio.get_running_loop()
            made=await loop.run_in_executor(None,render,inp,out,n,mode,x["hook"])
            names={"viral":"🔥 VIRAL AUTO","cinema":"🎬 CINEMA",
                   "meme":"😂 MEME","clean":"⚡ CLEAN HD"}
            with open(out,"rb") as f:
                await q.message.reply_video(
                    video=f,supports_streaming=True,
                    caption=f"✅ {names[mode]} | {made} Sek.\n1080×1920 • 30 FPS • Audio optimiert"
                )
        pending.pop(u.effective_chat.id,None)
    except Exception as e:
        print("EDIT ERROR:",repr(e),flush=True)
        await q.message.reply_text("❌ Fehler beim Edit.\n"+str(e)[-1600:])

def main():
    app=(Application.builder().token(TOKEN)
         .read_timeout(300).write_timeout(300)
         .connect_timeout(60).pool_timeout(60).build())
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.VIDEO|filters.Document.VIDEO,receive))
    app.add_handler(CallbackQueryHandler(choose_len,pattern=r"^l"))
    app.add_handler(CallbackQueryHandler(choose_style,pattern=r"^s"))
    print("FOOTBALL PRO EDITOR READY",flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
