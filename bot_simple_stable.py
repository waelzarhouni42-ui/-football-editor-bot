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
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN fehlt.")

pending = {}

def duration(path):
    r = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration",
         "-of","default=noprint_wrappers=1:nokey=1",path],
        capture_output=True,text=True,check=True
    )
    return float(r.stdout.strip())

def has_audio(path):
    r = subprocess.run(
        ["ffprobe","-v","error","-select_streams","a:0",
         "-show_entries","stream=codec_type",
         "-of","default=noprint_wrappers=1:nokey=1",path],
        capture_output=True,text=True
    )
    return bool(r.stdout.strip())

def make_edit(inp, out, seconds):
    d = duration(inp)
    seconds = max(1, min(int(seconds), int(d)))
    audio = has_audio(inp)

    # Robust single-pass edit: vertical 720x1280, 30 fps, no concat/filtergraph.
    vf = (
        "scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,setsar=1,fps=30,format=yuv420p"
    )

    cmd = [
        "ffmpeg","-y",
        "-ss","0",
        "-i",inp,
        "-t",str(seconds),
        "-vf",vf,
        "-c:v","libx264",
        "-preset","ultrafast",
        "-crf","25",
        "-threads","2",
    ]
    if audio:
        cmd += ["-c:a","aac","-b:a","128k","-ar","44100"]
    else:
        cmd += ["-an"]

    cmd += ["-movflags","+faststart",out]

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-3000:])
    return seconds

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Football Editor Bot\n\n"
        "Schick mir dein Fußballvideo und wähle danach die Länge.\n"
        "Nutze bitte nur Videos, die du verwenden darfst."
    )

async def receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media = update.message.video or update.message.document
    if not media:
        return
    pending[update.effective_chat.id] = media.file_id
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("30 Sek.", callback_data="30"),
         InlineKeyboardButton("60 Sek.", callback_data="60")],
        [InlineKeyboardButton("90 Sek.", callback_data="90"),
         InlineKeyboardButton("Maximal", callback_data="max")]
    ])
    await update.message.reply_text("Welche Länge?", reply_markup=kb)

async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    fid = pending.get(update.effective_chat.id)
    if not fid:
        await q.edit_message_text("Schick das Video bitte nochmal.")
        return

    await q.edit_message_text("⏳ Video wird bearbeitet ...")

    try:
        f = await context.bot.get_file(fid)
        with tempfile.TemporaryDirectory() as td:
            inp = str(Path(td) / "input.mp4")
            out = str(Path(td) / "edit.mp4")
            await f.download_to_drive(inp)

            d = duration(inp)
            requested = int(d) if q.data == "max" else int(q.data)
            requested = min(requested, int(d), 120)

            loop = asyncio.get_running_loop()
            made = await loop.run_in_executor(None, make_edit, inp, out, requested)

            with open(out, "rb") as video:
                await q.message.reply_video(
                    video=video,
                    supports_streaming=True,
                    caption=f"✅ Fertig – {made} Sek.\n\n"
                            "Tipp: Ergänze einen eigenen Hook, Kommentar oder Analyse, "
                            "damit dein Beitrag mehr eigenen Mehrwert hat."
                )
        pending.pop(update.effective_chat.id, None)

    except Exception as e:
        print("EDIT ERROR:", repr(e), flush=True)
        await q.message.reply_text(
            "❌ Bearbeitung fehlgeschlagen.\n"
            f"{str(e)[-1800:]}"
        )

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive))
    app.add_handler(CallbackQueryHandler(choose, pattern=r"^(30|60|90|max)$"))
    print("BOT READY", flush=True)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
