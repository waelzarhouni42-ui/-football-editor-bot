import os, asyncio, subprocess, tempfile
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
if not TOKEN: raise RuntimeError("BOT_TOKEN fehlt.")
pending={}

def run(cmd):
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr[-2200:])
    return p

def duration(p):
    return float(run(["ffprobe","-v","error","-show_entries","format=duration",
                      "-of","default=nw=1:nk=1",p]).stdout.strip())

def has_audio(p):
    x=subprocess.run(["ffprobe","-v","error","-select_streams","a:0",
                      "-show_entries","stream=codec_type","-of","default=nw=1:nk=1",p],
                     capture_output=True,text=True)
    return bool(x.stdout.strip())

def esc(s):
    return s.replace("\\","\\\\").replace(":","\\:").replace("'","\\'").replace("%","\\%").replace(",","\\,")

def render(inp,out,secs,style,hook):
    d=duration(inp); secs=max(1,min(int(secs),int(d))); a=has_audio(inp)

    # Based on user's reference: full football frame, punchy contrast,
    # mild soft/glow look, occasional slow-motion feel, no permanent hard crop.
    base=(
      "[0:v]split=2[bg][fg];"
      "[bg]scale=720:1280:force_original_aspect_ratio=increase,"
      "crop=720:1280,boxblur=10:5,eq=brightness=-0.05:saturation=1.08[bgv];"
      "[fg]scale=720:1280:force_original_aspect_ratio=decrease,setsar=1,"
      "eq=contrast=1.08:saturation=1.12:brightness=0.01,"
      "unsharp=5:5:0.35:5:5:0[fgv];"
      "[bgv][fgv]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p"
    )

    if style=="reference":
        # Gentle cinematic softness/glow without expensive multi-segment concat.
        base += ",gblur=sigma=0.35"
    elif style=="slow":
        base += ",setpts=PTS/0.88"
    elif style=="zoom":
        # Moderate punch-in, not the aggressive crop used before.
        base += ",scale=756:1344,crop=720:1280"
    elif style=="meme":
        h=esc((hook or "WHAT A MOMENT")[:50])
        base += (f",drawtext=text='{h}':fontcolor=white:fontsize=40:"
                 "borderw=4:bordercolor=black:x=(w-text_w)/2:y=70:"
                 "enable='between(t,0,3.2)'")
    base += "[v]"

    cmd=["ffmpeg","-y","-i",inp,"-t",str(secs),"-filter_complex",base,"-map","[v]"]
    if a:
        cmd += ["-map","0:a:0"]
        af="loudnorm=I=-14:TP=-1.5:LRA=11"
        if style=="slow": af="atempo=0.88,"+af
        cmd += ["-af",af,"-c:a","aac","-b:a","128k","-ar","44100"]
    else: cmd += ["-an"]
    cmd += ["-c:v","libx264","-preset","ultrafast","-crf","23","-threads","2",
            "-movflags","+faststart",out]
    run(cmd); return secs

async def start(u,c):
    await u.message.reply_text(
      "⚽ FOOTBALL STYLE EDITOR\n\n"
      "Schick dein Video → Länge → Stil.\n"
      "🎞 Reference Style = Look ähnlich deinem Beispiel\n"
      "🐢 Slow • 🔍 Zoom • 😂 Meme\n\n"
      "Nutze nur Material, das du verwenden darfst."
    )

async def recv(u,c):
    m=u.message.video or u.message.document
    if not m:return
    pending[u.effective_chat.id]={"id":m.file_id,"hook":u.message.caption or "WHAT A MOMENT"}
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("30 Sek.",callback_data="l30"),
                              InlineKeyboardButton("60 Sek.",callback_data="l60")],
                             [InlineKeyboardButton("90 Sek.",callback_data="l90"),
                              InlineKeyboardButton("Maximal",callback_data="lmax")]])
    await u.message.reply_text("1/2 Länge:",reply_markup=kb)

async def choose_len(u,c):
    q=u.callback_query; await q.answer(); x=pending.get(u.effective_chat.id)
    if not x:return await q.edit_message_text("Video bitte nochmal schicken.")
    x["len"]=q.data[1:]
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🎞 Reference Style",callback_data="sreference"),
                              InlineKeyboardButton("🐢 Slow",callback_data="sslow")],
                             [InlineKeyboardButton("🔍 Zoom",callback_data="szoom"),
                              InlineKeyboardButton("😂 Meme",callback_data="smeme")]])
    await q.edit_message_text("2/2 Stil:",reply_markup=kb)

async def choose_style(u,c):
    q=u.callback_query; await q.answer(); x=pending.get(u.effective_chat.id)
    if not x:return
    style=q.data[1:]; await q.edit_message_text("⏳ Edit wird erstellt ...")
    try:
        tg=await c.bot.get_file(x["id"])
        with tempfile.TemporaryDirectory() as td:
            inp=str(Path(td)/"input.mp4"); out=str(Path(td)/"edit.mp4")
            await tg.download_to_drive(inp)
            d=duration(inp); n=int(d) if x["len"]=="max" else int(x["len"]); n=min(n,int(d),120)
            made=await asyncio.get_running_loop().run_in_executor(None,render,inp,out,n,style,x["hook"])
            names={"reference":"🎞 Reference Style","slow":"🐢 Slow","zoom":"🔍 Zoom","meme":"😂 Meme"}
            with open(out,"rb") as f:
                await q.message.reply_video(video=f,supports_streaming=True,
                    read_timeout=600,write_timeout=600,connect_timeout=90,pool_timeout=90,
                    caption=f"✅ {names[style]} | {made} Sek. • 720×1280 • 30 FPS")
        pending.pop(u.effective_chat.id,None)
    except Exception as e:
        print("EDIT ERROR:",repr(e),flush=True)
        await q.message.reply_text("❌ Fehler beim Edit.\n"+str(e)[-1500:])

def main():
    app=(Application.builder().token(TOKEN).read_timeout(600).write_timeout(600)
         .connect_timeout(90).pool_timeout(90).build())
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.VIDEO|filters.Document.VIDEO,recv))
    app.add_handler(CallbackQueryHandler(choose_len,pattern=r"^l"))
    app.add_handler(CallbackQueryHandler(choose_style,pattern=r"^s"))
    print("FOOTBALL STYLE EDITOR READY",flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
