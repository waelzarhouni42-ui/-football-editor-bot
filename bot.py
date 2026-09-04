import os
import asyncio
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_HOOK = os.getenv("DEFAULT_HOOK", "WHAT A MOMENT")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN fehlt. Trage BOT_TOKEN bei Railway unter Variables ein.")
pending = {}

def probe_duration(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())

def has_audio(path):
    r = subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_type","-of","default=noprint_wrappers=1:nokey=1",path], capture_output=True, text=True)
    return bool(r.stdout.strip())

def esc(text):
    return text.replace("\\","\\\\").replace(":","\\:").replace("'","\\'").replace("%","\\%").replace(",","\\,")

def build_segments(duration, target):
    target = max(1, min(target, int(duration)))
    if duration <= target + 1:
        return [(0.0, float(target), 1.0)]
    count = 6 if target >= 60 else 5
    seg_len = target / count
    anchors = [0.03,0.20,0.38,0.56,0.73,0.88][:count]
    out=[]
    for i,a in enumerate(anchors):
        start=min(max(0.0,duration*a),max(0.0,duration-seg_len-0.1))
        speed=0.90 if i==2 and seg_len>=4 else 1.0
        out.append((start,seg_len,speed))
    return out

def edit_video(input_path, output_path, hook, target):
    duration=probe_duration(input_path)
    target=max(1,min(target,int(duration)))
    segments=build_segments(duration,target)
    audio=has_audio(input_path)
    filters=[]; parts=[]
    for i,(start,seg_len,speed) in enumerate(segments):
        v=f"v{i}"
        vf=f"[0:v]trim=start={start}:duration={seg_len},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        if i%2==0: vf += ",scale=1102:1958,crop=1080:1920,setsar=1"
        if speed!=1.0: vf += f",setpts=PTS/{speed}"
        vf += ",setsar=1,format=yuv420p"
        filters.append(vf+f"[{v}]")
        if audio:
            a=f"a{i}"; af=f"[0:a]atrim=start={start}:duration={seg_len},asetpts=PTS-STARTPTS"
            if speed!=1.0: af += f",atempo={speed}"
            filters.append(af+f"[{a}]"); parts.append(f"[{v}][{a}]")
        else: parts.append(f"[{v}]")
    if audio: filters.append("".join(parts)+f"concat=n={len(segments)}:v=1:a=1[vcat][acat]")
    else: filters.append("".join(parts)+f"concat=n={len(segments)}:v=1:a=0[vcat]")
    hook=esc(hook[:70])
    filters.append("[vcat]"+f"drawtext=text='{hook}':fontcolor=white:fontsize=58:borderw=4:bordercolor=black:x=(w-text_w)/2:y=120:enable='between(t,0,3.5)',"+"drawtext=text='WATCH TILL THE END':fontcolor=white:fontsize=40:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-190:enable='between(t,3.5,7)'[vout]")
    cmd=["ffmpeg","-y","-i",input_path,"-filter_complex",";".join(filters),"-map","[vout]"]
    if audio: cmd += ["-map","[acat]"]
    cmd += ["-c:v","libx264","-preset","veryfast","-crf","22","-pix_fmt","yuv420p"]
    if audio: cmd += ["-c:a","aac","-b:a","128k"]
    cmd += ["-movflags","+faststart","-shortest",output_path]
    subprocess.run(cmd,check=True,capture_output=True)

async def start(update, context):
    await update.message.reply_text("Football Editor Bot\n\nSchick mir ein Fußballvideo. Danach wählst du die gewünschte Länge.\n\nBitte nutze nur Material, das du verwenden darfst.")

async def receive_video(update, context):
    msg=update.message; media=msg.video or msg.document
    if not media: return
    pending[msg.chat_id]={"file_id":media.file_id,"hook":(msg.caption or DEFAULT_HOOK).strip()[:70]}
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("30 Sek.",callback_data="len_30"),InlineKeyboardButton("60 Sek.",callback_data="len_60")],[InlineKeyboardButton("90 Sek.",callback_data="len_90"),InlineKeyboardButton("Maximal",callback_data="len_9999")]])
    await msg.reply_text("Welche Länge möchtest du?",reply_markup=kb)

async def choose_length(update, context):
    q=update.callback_query; await q.answer(); chat_id=q.message.chat_id; data=pending.get(chat_id)
    if not data:
        await q.edit_message_text("Kein Video gefunden. Schick das Video bitte nochmal."); return
    target=int(q.data.split("_")[1]); await q.edit_message_text("Ich erstelle deinen Edit ...")
    try:
        tg_file=await context.bot.get_file(data["file_id"])
        with tempfile.TemporaryDirectory() as td:
            inp=str(Path(td)/"input.mp4"); out=str(Path(td)/"football_edit.mp4")
            await tg_file.download_to_drive(inp); duration=probe_duration(inp)
            target=min(int(duration),120) if target==9999 else min(target,int(duration))
            loop=asyncio.get_running_loop(); await loop.run_in_executor(None,edit_video,inp,out,data["hook"],target)
            with open(out,"rb") as f:
                await q.message.reply_video(video=f,supports_streaming=True,caption=f"Fertig – ca. {target} Sek.")
        pending.pop(chat_id,None)
    except subprocess.CalledProcessError as e:
        err=e.stderr.decode("utf-8",errors="ignore") if isinstance(e.stderr,bytes) else str(e.stderr or "")
        print("FFmpeg error:",err); await q.message.reply_text("FFmpeg konnte das Video nicht bearbeiten.\n\n"+err[-2500:]); pending.pop(chat_id,None)
    except Exception as e:
        print(type(e).__name__,str(e)); await q.message.reply_text(f"Fehler: {type(e).__name__}: {e}"); pending.pop(chat_id,None)

def main():
    app=(Application.builder().token(BOT_TOKEN).read_timeout(300).write_timeout(300).connect_timeout(300).pool_timeout(300).build())
    app.add_handler(CommandHandler("start",start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO,receive_video))
    app.add_handler(CallbackQueryHandler(choose_length,pattern=r"^len_"))
    print("Football Editor Bot läuft.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
