
import os
import asyncio
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DEFAULT_HOOK = os.getenv("DEFAULT_HOOK", "WHAT A MOMENT 🤯⚽")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN fehlt. Trage ihn in die .env Datei ein.")

# Temporäre Daten pro Chat
pending = {}

def probe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)

def safe_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
            .replace(":", "\\:")
            .replace("'", "\\'")
            .replace("%", "\\%")
    )

def build_segments(duration: float, target: int):
    """
    Erstellt mehrere unterschiedliche Ausschnitte aus dem Video.
    Wir verteilen sie über Anfang, Mitte und Ende, statt einfach nur
    die ersten X Sekunden zu nehmen.
    """
    target = min(target, max(6, int(duration)))
    if duration <= target + 2:
        return [(0, duration, 1.0)]

    # 5 Segmente für einen dynamischeren Edit
    seg_count = 5 if target >= 30 else 4
    per = target / seg_count

    # Positionen über das gesamte Video verteilt
    anchors = [0.04, 0.24, 0.47, 0.69, 0.86][:seg_count]
    segments = []

    for i, a in enumerate(anchors):
        seg_len = per
        start = max(0, min(duration - seg_len - 0.2, duration * a))
        speed = 1.0

        # Ein kurzer Slow-Motion-Part in der Mitte
        if i == 2 and seg_len >= 4:
            speed = 0.85

        segments.append((start, seg_len, speed))

    return segments

def edit_video(input_path: str, output_path: str, hook: str, target_seconds: int):
    duration = probe_duration(input_path)
    target_seconds = min(target_seconds, int(duration))
    segments = build_segments(duration, target_seconds)

    filters = []
    concat_inputs = []

    for i, (start, seg_len, speed) in enumerate(segments):
        vlabel = f"v{i}"
        alabel = f"a{i}"

        # Unterschiedliche leichte Bildbewegung je Segment
        zoom = 1.00 + (0.02 if i % 2 == 0 else 0.00)

        vf = (
            f"[0:v]trim=start={start}:duration={seg_len},setpts=PTS-STARTPTS,"
            f"scale=1080:1920:force_original_aspect_ratio=increase,"
            f"crop=1080:1920,"
            f"scale=iw*{zoom}:ih*{zoom},crop=1080:1920,"
            f"eq=contrast=1.04:saturation=1.06"
        )

        # Slow motion mit korrekter Zeitbasis
        if speed != 1.0:
            vf += f",setpts=PTS/{speed}"

        vf += f"[{vlabel}]"
        filters.append(vf)

        af = f"[0:a]atrim=start={start}:duration={seg_len},asetpts=PTS-STARTPTS"
        if speed != 1.0:
            # atempo unterstützt 0.5 bis 2.0
            af += f",atempo={speed}"
        af += f"[{alabel}]"
        filters.append(af)

        concat_inputs.append(f"[{vlabel}][{alabel}]")

    concat_label_v = "vcat"
    concat_label_a = "acat"
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a=1[{concat_label_v}][{concat_label_a}]"
    )

    hook_safe = safe_drawtext(hook)

    # Eigene redaktionelle Overlays
    final_v = (
        f"[{concat_label_v}]"
        f"drawtext=text='{hook_safe}':fontcolor=white:fontsize=62:"
        f"borderw=4:bordercolor=black:x=(w-text_w)/2:y=110:"
        f"enable='between(t,0,3.2)',"
        f"drawtext=text='WATCH TILL THE END 👀':fontcolor=white:fontsize=42:"
        f"borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-190:"
        f"enable='between(t,3.2,6.5)'"
        f"[vout]"
    )
    filters.append(final_v)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]",
        "-map", f"[{concat_label_a}]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        "-shortest",
        output_path,
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Football Editor Bot V2\n\n"
        "Schick mir ein Fußballvideo. Danach wählst du die gewünschte Länge.\n\n"
        "Der Bot erstellt einen eigenständigeren Edit mit:\n"
        "• mehreren Szenen aus verschiedenen Stellen\n"
        "• 9:16 TikTok-Format\n"
        "• eigenem Hook-Text\n"
        "• schnellen Schnitten\n"
        "• leichtem Zoom\n"
        "• einem kurzen Slow-Motion-Part\n"
        "• zusätzlicher Texteinblendung\n\n"
        "💡 Tipp: Schreib deinen Hook als Bildunterschrift zum Video.\n"
        "Beispiel: MESSI WAS DIFFERENT THAT NIGHT 🤯\n\n"
        "Bitte nutze nur Material, das du verwenden darfst."
    )

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media = msg.video or msg.document
    if not media:
        return

    hook = (msg.caption or DEFAULT_HOOK).strip()[:80]

    pending[msg.chat_id] = {
        "file_id": media.file_id,
        "hook": hook,
    }

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30 Sek.", callback_data="len_30"),
            InlineKeyboardButton("60 Sek.", callback_data="len_60"),
        ],
        [
            InlineKeyboardButton("90 Sek.", callback_data="len_90"),
            InlineKeyboardButton("Maximal", callback_data="len_9999"),
        ]
    ])

    await msg.reply_text("Welche Länge möchtest du?", reply_markup=kb)

async def choose_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = q.message.chat_id
    data = pending.get(chat_id)

    if not data:
        await q.edit_message_text("❌ Kein Video gefunden. Schick mir das Video bitte nochmal.")
        return

    target = int(q.data.split("_")[1])

    await q.edit_message_text("⏳ Ich erstelle deinen V2-Edit …")

    try:
        tg_file = await context.bot.get_file(data["file_id"])

        with tempfile.TemporaryDirectory() as td:
            in_path = str(Path(td) / "input.mp4")
            out_path = str(Path(td) / "football_edit_v2.mp4")

            await tg_file.download_to_drive(in_path)

            duration = probe_duration(in_path)
            if target == 9999:
                target = min(int(duration), 120)

            target = min(target, int(duration))

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                edit_video,
                in_path,
                out_path,
                data["hook"],
                target
            )

            await q.message.reply_video(
                video=open(out_path, "rb"),
                supports_streaming=True,
                caption=(
                    f"✅ Fertig – ca. {target} Sek.\n\n"
                    "Der Edit wurde aus mehreren Szenen neu zusammengesetzt. "
                    "Das kann den Inhalt eigenständiger machen, garantiert aber keine "
                    "TikTok-Freigabe und ersetzt keine Nutzungsrechte."
                ),
            )

    except subprocess.CalledProcessError as e:
    error = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
    await q.message.reply_text(
        "❌ Echter FFmpeg-Fehler:\n\n" + error[-3000:]
    )
    pending.pop(chat_id, None)

except Exception as e:
except Exception as e:
    await q.message.reply_text(f"❌ Fehler: {type(e).__name__}: {e}")
def main()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(300)
        .pool_timeout(300)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO, choose_length))
    app.add_handler(CallbackQueryHandler(choose_length_callback))
    print("Football Editor Bot V2 läuft ...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, receive_video))
    app.add_handler(CallbackQueryHandler(choose_length, pattern=r"^len_"))
    print("Football Editor Bot V2 läuft …")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
