import os,asyncio,subprocess,tempfile,math
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import Application,CommandHandler,MessageHandler,CallbackQueryHandler,ContextTypes,filters
load_dotenv(); TOKEN=os.getenv("BOT_TOKEN")
if not TOKEN: raise RuntimeError("BOT_TOKEN fehlt.")
pending={}
def run(c):
 p=subprocess.run(c,capture_output=True,text=True)
 if p.returncode: raise RuntimeError(p.stderr[-2200:])
 return p
def dur(p): return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",p]).stdout.strip())
def audio(p):
 x=subprocess.run(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=codec_type","-of","default=nw=1:nk=1",p],capture_output=True,text=True); return bool(x.stdout.strip())
def esc(s): return s.replace("\\","\\\\").replace(":","\\:").replace("'","\\'").replace("%","\\%").replace(",","\\,")
def cuts(inp,d):
 try:
  p=subprocess.run(["ffmpeg","-hide_banner","-i",inp,"-vf","select='gt(scene,0.32)',metadata=print","-an","-f","null","-"],capture_output=True,text=True,timeout=90)
  a=[]
  for line in p.stderr.splitlines():
   if "pts_time:" in line:
    try:
     t=float(line.split("pts_time:")[1].split()[0])
     if 1<t<d-1 and (not a or t-a[-1]>2): a.append(t)
    except: pass
  return a[:24]
 except: return []
def render(inp,out,target,hook):
 d=dur(inp); target=max(1,min(int(target),int(d))); ha=audio(inp)
 cs=cuts(inp,d) or [d*x for x in (.05,.2,.36,.52,.68,.84)]
 count=max(3,min(6,math.ceil(target/9))); sl=target/count
 seg=[]
 for i in range(count):
  st=max(0,min(cs[min(i*len(cs)//count,len(cs)-1)],d-sl-.1))
  seg.append((st,sl,"slow" if i==count//2 else ("zoom" if i%2 else "normal")))
 fs=[]; joins=[]
 for i,(st,ln,k) in enumerate(seg):
  v=f"v{i}"; ch=f"[0:v]trim=start={st}:duration={ln},setpts=PTS-STARTPTS,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30,eq=contrast=1.08:saturation=1.12,unsharp=5:5:0.3:5:5:0"
  if k=="zoom": ch+=",scale=770:1369,crop=720:1280"
  if k=="slow": ch+=",setpts=PTS/0.55"
  ch+=",setsar=1"
  fs.append(ch+f",format=yuv420p[{v}]")
  if ha:
   a=f"a{i}"; ac=f"[0:a]atrim=start={st}:duration={ln},asetpts=PTS-STARTPTS"
   if k=="slow": ac+=",atempo=0.55"
   fs.append(ac+f"[{a}]"); joins.append(f"[{v}][{a}]")
  else: joins.append(f"[{v}]")
 if ha: fs.append("".join(joins)+f"concat=n={count}:v=1:a=1[vcat][acat]")
 else: fs.append("".join(joins)+f"concat=n={count}:v=1:a=0[vcat]")
 h=esc((hook or "WATCH THIS")[:45]); fs.append(f"[vcat]drawtext=text='{h}':fontcolor=white:fontsize=42:borderw=4:bordercolor=black:x=(w-text_w)/2:y=70:enable='between(t,0,2.8)'[vout]")
 cmd=["ffmpeg","-y","-i",inp,"-filter_complex",";".join(fs),"-map","[vout]"]
 if ha: cmd+=["-map","[acat]","-c:a","aac","-b:a","128k"]
 else: cmd+=["-an"]
 cmd+=["-c:v","libx264","-preset","ultrafast","-crf","23","-threads","2","-movflags","+faststart","-shortest",out]
 run(cmd); return count
async def start(u,c): await u.message.reply_text("⚽ FOOTBALL EDITOR V2\n\n🎬 Szenenanalyse\n✂️ mehrere Cuts\n🐢 starke Slow Motion 0.55x\n🔍 Punch-Zoom\n✨ Kontrast + Schärfe\n📱 9:16 Full Screen\n\nVideo schicken. Hook optional als Caption.\nNutze nur Material, das du verwenden darfst.")
async def recv(u,c):
 m=u.message.video or u.message.document
 if not m:return
 pending[u.effective_chat.id]={"id":m.file_id,"hook":u.message.caption or "WATCH THIS"}
 kb=InlineKeyboardMarkup([[InlineKeyboardButton("30 Sek.",callback_data="30"),InlineKeyboardButton("60 Sek.",callback_data="60")],[InlineKeyboardButton("90 Sek.",callback_data="90"),InlineKeyboardButton("Maximal",callback_data="max")]])
 await u.message.reply_text("Welche Länge?",reply_markup=kb)
async def edit(u,c):
 q=u.callback_query; await q.answer(); x=pending.get(u.effective_chat.id)
 if not x:return
 await q.edit_message_text("🎬 Szenen werden analysiert und bearbeitet ...")
 try:
  tg=await c.bot.get_file(x["id"])
  with tempfile.TemporaryDirectory() as td:
   inp=str(Path(td)/"in.mp4"); out=str(Path(td)/"v2.mp4"); await tg.download_to_drive(inp)
   d=dur(inp); n=int(d) if q.data=="max" else int(q.data); n=min(n,int(d),120)
   count=await asyncio.get_running_loop().run_in_executor(None,render,inp,out,n,x["hook"])
   with open(out,"rb") as f: await q.message.reply_video(video=f,supports_streaming=True,read_timeout=600,write_timeout=600,connect_timeout=90,pool_timeout=90,caption=f"✅ V2 • {count} Szenen • starke Slow Motion + Zoom • 720×1280")
  pending.pop(u.effective_chat.id,None)
 except Exception as e:
  print("EDIT ERROR",repr(e),flush=True); await q.message.reply_text("❌ Fehler\n"+str(e)[-1500:])
def main():
 app=Application.builder().token(TOKEN).read_timeout(600).write_timeout(600).connect_timeout(90).pool_timeout(90).build()
 app.add_handler(CommandHandler("start",start)); app.add_handler(MessageHandler(filters.VIDEO|filters.Document.VIDEO,recv)); app.add_handler(CallbackQueryHandler(edit,pattern=r"^(30|60|90|max)$"))
 print("V2 READY",flush=True); app.run_polling(drop_pending_updates=True)
if __name__=="__main__": main()
