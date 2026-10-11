importimport asyncio
import os
import sqlite3
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask, render_template_string, request
import yt_dlp

# --- 0. إعداد خادم الويب ولوحة التحكم ---
app = Flask("JokerDashboard")

html_template = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>Joker Bot - Dashboard</title>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: Tahoma, sans-serif; text-align: center; padding: 50px; }
        .card { background: #1e293b; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 15px; }
        h1 { color: #38bdf8; }
        input, button { width: 100%; padding: 12px; margin: 10px 0; border-radius: 8px; border: none; font-size: 16px; }
        input { background: #334155; color: white; }
        button { background: #6366f1; color: white; font-weight: bold; cursor: pointer; }
        .success { color: #4ade80; margin-top: 15px; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🌟 لوحة تحكم بوت الجوكر</h1>
        <form method="POST">
            <label>🆔 معرف السيرفر (Guild ID):</label>
            <input type="text" name="guild_id" required placeholder="أدخل آي دي السيرفر">
            <label>📢 قناة الترحيب (Welcome ID):</label>
            <input type="text" name="welcome_id" placeholder="أدخل آي دي القناة">
            <label>🎫 قسم التذاكر (Ticket ID):</label>
            <input type="text" name="ticket_id" placeholder="أدخل آي دي القسم">
            <button type="submit">💾 حفظ الإعدادات</button>
        </form>
        {% if success %}<div class="success">✅ تم الحفظ بنجاح!</div>{% endif %}
    </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def dashboard():
  success = False
  if request.method == "POST":
    guild_id = request.form.get("guild_id")
    welcome_id = request.form.get("welcome_id")
    ticket_id = request.form.get("ticket_id")
    if guild_id:
      cursor.execute(
          "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)",
          (guild_id,),
      )
      if welcome_id:
        cursor.execute(
            "UPDATE guild_settings SET welcome_channel_id = ? WHERE guild_id"
            " = ?",
            (welcome_id, guild_id),
        )
      if ticket_id:
        cursor.execute(
            "UPDATE guild_settings SET ticket_category_id = ? WHERE guild_id ="
            " ? ",
            (ticket_id, guild_id),
        )
      db.commit()
      success = True
  return render_template_string(html_template, success=success)


def run_web():
  app.run(host="0.0.0.0", port=8080)


def keep_alive():
  t = Thread(target=run_web)
  t.daemon = True
  t.start()


# --- 1. قاعدة البيانات ---
db = sqlite3.connect("joker_bot_complete.db", check_same_thread=False)
cursor = db.cursor()
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        welcome_channel_id INTEGER,
        ticket_category_id INTEGER
    )
"""
)
db.commit()

# --- 2. إعدادات البوت ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
}
ffmpeg_options = {
    'options': '-vn',
    'before_options': (
        '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
    ),
}
ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):

  def __init__(self, source, *, data, volume=0.5):
    super().__init__(source, volume)
    self.data = data
    self.title = data.get('title')
    self.url = data.get('url')

  @classmethod
  async def from_url(cls, url, *, loop=None, stream=True):
    loop = loop or asyncio.get_event_loop()
    data = await loop.run_in_executor(
        None, lambda: ytdl.extract_info(url, download=not stream)
    )
    if 'entries' in data:
      data = data['entries'][0]
    filename = data['url'] if stream else ytdl.prepare_filename(data)
    return cls(
        discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data
    )


class TicketCloseView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="إغلاق التذكرة 🔒",
      style=discord.ButtonStyle.red,
      custom_id="close_ticket",
  )
  async def close_ticket(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.send_message(
        "🔒 جاري إغلاق وحذف التذكرة...", ephemeral=True
    )
    await asyncio.sleep(3)
    try:
      await interaction.channel.delete()
    except:
      pass


class TicketView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="فتح تذكرة دعم 🎫",
      style=discord.ButtonStyle.green,
      custom_id="open_ticket",
  )
  async def open_ticket(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    guild = interaction.guild
    cursor.execute(
        "SELECT ticket_category_id FROM guild_settings WHERE guild_id = ?",
        (guild.id,),
    )
    res = cursor.fetchone()
    cat = (
        guild.get_channel(res[0])
        if res and res[0]
        else discord.utils.get(guild.categories, name="🎫 ┃ التذاكر")
    )
    if not cat:
      cat = await guild.create_category("🎫 ┃ التذاكر")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True
        ),
    }
    ch = await guild.create_text_channel(
        f"ticket-{interaction.user.name}", category=cat, overwrites=overwrites
    )
    await interaction.response.send_message(
        f"✅ تم فتح تذكرتك: {ch.mention}", ephemeral=True
    )
    embed = discord.Embed(
        title="🎫 تذكرة دعم جديدة",
        description=f"مرحباً بك {interaction.user.mention}!",
        color=discord.Color.blue(),
    )
    await ch.send(embed=embed, view=TicketCloseView())


@bot.event
async def on_ready():
  print(f"🔥 البوت شغال: {bot.user.name}")
  try:
    await bot.tree.sync()
  except:
    pass
  await bot.change_presence(activity=discord.Game(name="Joker Bot | /help"))


@bot.event
async def on_member_join(member):
  cursor.execute(
      "SELECT welcome_channel_id FROM guild_settings WHERE guild_id = ?",
      (member.guild.id,),
  )
  res = cursor.fetchone()
  if res and res[0]:
    ch = member.guild.get_channel(res[0])
    if ch:
      embed = discord.Embed(
          title="✨ أهلاً بك!",
          description=f"نورتنا يا {member.mention}",
          color=discord.Color.gold(),
      )
      await ch.send(embed=embed)


@bot.tree.command(name="help", description="عرض الأوامر ومعلومات البوت")
async def help_command(interaction: discord.Interaction):
  embed = discord.Embed(
      title="🌟 Joker Bot - All-in-One",
      description=(
          "» Help `/help`\n» Tickets `/setup-tickets`\n» Play `/play`\n» Stop"
          " `/stop`\n\n**Developer:** <@1506333213554118827>"
      ),
      color=discord.Color.from_rgb(88, 101, 242),
  )
  await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup-tickets", description="إرسال لوحة التذاكر")
@app_commands.default_permissions(administrator=True)
async def setup_tickets(
    interaction: discord.Interaction,
    category: discord.CategoryChannel = None,
):
  if category:
    cursor.execute(
        "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)",
        (interaction.guild.id,),
    )
    cursor.execute(
        "UPDATE guild_settings SET ticket_category_id = ? WHERE guild_id = ?",
        (category.id, interaction.guild.id),
    )
    db.commit()
  embed = discord.Embed(
      title="🎫 قسم الدعم الفني",
      description="اضغط الزر أدناه لفتح تذكرة.",
      color=discord.Color.blue(),
  )
  await interaction.channel.send(embed=embed, view=TicketView())
  await interaction.response.send_message(
      "✅ تم إرسال لوحة التذاكر!", ephemeral=True
  )


@bot.tree.command(name="play", description="تشغيل أغنية")
async def play(interaction: discord.Interaction, search: str):
  if not interaction.user.voice:
    await interaction.response.send_message(
        "❌ اتصل بروم صوتي أولاً!", ephemeral=True
    )
    return
  await interaction.response.defer()
  vc = (
      interaction.guild.voice_client
      or await interaction.user.voice.channel.connect()
  )
  try:
    player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
    if vc.is_playing():
      vc.stop()
    vc.play(player)
    await interaction.followup.send(f"🎶 جاري تشغيل: **{player.title}**")
  except Exception as e:
    await interaction.followup.send(f"❌ خطأ: `{str(e)}`")


@bot.tree.command(name="stop", description="إيقاف الموسيقى")
async def stop(interaction: discord.Interaction):
  if interaction.guild.voice_client:
    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("⏹️ تم الإيقاف.", ephemeral=True)
  else:
    await interaction.response.send_message(
        "❌ البوت مو بروم صوتي!", ephemeral=True
    )


# --- التشغيل السحابي ---
if __name__ == "__main__":
  keep_alive()
  bot.run(os.getenv("TOKEN"))
