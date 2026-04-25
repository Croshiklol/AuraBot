import os, asyncio, logging, sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.enums import ParseMode
from yt_dlp import YoutubeDL
from shazamio import Shazam
from config import Config

# --- НАСТРОЙКИ ---
Config.validate()
TOKEN = Config.TOKEN
ADMIN_ID = Config.ADMIN_ID
BOT_USERNAME = Config.BOT_USERNAME
CACHE_DIR = Config.CACHE_DIR
LOG_FILE = Config.LOG_FILE

if not os.path.exists(CACHE_DIR): 
    os.makedirs(CACHE_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
logger = logging.getLogger("AuraBot")

# --- БАЗЫ ДАННЫХ ---
conn_u = sqlite3.connect("users.db", check_same_thread=False)
conn_m = sqlite3.connect("music_data.db", check_same_thread=False)

def init_dbs():
    conn_u.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
    conn_u.commit()
    conn_m.execute("""
    CREATE TABLE IF NOT EXISTS cache (
        track_id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT UNIQUE, title TEXT, performer TEXT, original_url TEXT UNIQUE
    )""")
    conn_m.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        user_id INTEGER, track_id INTEGER, PRIMARY KEY (user_id, track_id)
    )""")
    conn_m.commit()

init_dbs()

bot = Bot(token=TOKEN)
dp = Dispatcher()
shazam_client = Shazam()
temp_search = {}

class AdState(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    waiting_for_link = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def download_track(url):
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{CACHE_DIR}/%(id)s.%(ext)s',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
        'quiet': True, 'noplaylist': True
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info).replace('.webm', '.mp3').replace('.m4a', '.mp3')
        return path, info.get('title', 'Unknown'), info.get('uploader', 'Aura Music')

def get_kb(t_id, u_id, title):
    builder = InlineKeyboardBuilder()
    res = conn_m.execute("SELECT 1 FROM favorites WHERE user_id = ? AND track_id = ?", (u_id, t_id)).fetchone()
    builder.button(text="❤️" if res else "🤍", callback_data=f"like_{t_id}")
    share_link = f"https://t.me/{BOT_USERNAME}?start={t_id}"
    builder.button(text="🚀 Поделиться", url=f"https://t.me/share/url?url={share_link}&text=Послушай этот трек!")
    builder.button(text="📂 Плейлист", callback_data="my_playlist")
    builder.adjust(2, 1)
    return builder.as_markup()

# --- АДМИН-КОМАНДЫ ---

@dp.message(Command("stats"), F.from_user.id == ADMIN_ID)
async def cmd_stats(message: types.Message):
    u_count = conn_u.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    m_count = conn_m.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    await message.answer(f"📊 **Статистика:**\n\n👤 Юзеров: `{u_count}`\n🎵 В кэше: `{m_count}`", parse_mode=ParseMode.MARKDOWN)

@dp.message(Command("broadcast"), F.from_user.id == ADMIN_ID)
async def start_bc(message: types.Message, state: FSMContext):
    await state.set_state(AdState.waiting_for_text)
    await message.answer("📝 **Рассылка:** Введи текст сообщения:")

@dp.message(AdState.waiting_for_text)
async def bc_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(AdState.waiting_for_photo)
    await message.answer("📸 **Шаг 3:** Пришли фото для рассылки или напиши 'нет':")

@dp.message(AdState.waiting_for_photo)
async def bc_photo(message: types.Message, state: FSMContext):
    if message.photo:
        await state.update_data(photo=message.photo[-1].file_id)
    else:
        await state.update_data(photo=None)
    await state.set_state(AdState.waiting_for_link)
    await message.answer("🔗 Введи ссылку для кнопки (или 'нет'):")

@dp.message(AdState.waiting_for_link)
async def bc_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    link = message.text.lower()
    kb = None
    if link != "нет":
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text="🔗 Перейти", url=message.text)
        kb = kb_builder.as_markup()

    users = conn_u.execute("SELECT user_id FROM users").fetchall()
    count = 0
    for u in users:
        try:
            if data.get('photo'):
                await bot.send_photo(u[0], data['photo'], caption=data['text'], reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            else:
                await bot.send_message(u[0], data['text'], reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            count += 1
            await asyncio.sleep(0.05)
        except: pass
    await state.clear()
    await message.answer(f"✅ Рассылка завершена! Получили: {count}")

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    # Добавляем юзера в БД
    conn_u.execute("INSERT OR IGNORE INTO users VALUES (?)", (message.from_user.id,))
    conn_u.commit()

    # Проверка на переход по глубокой ссылке (диплинк)
    args = command.args
    if args and args.isdigit():
        t_id = int(args)
        res = conn_m.execute("SELECT file_id, title FROM cache WHERE track_id = ?", (t_id,)).fetchone()
        if res:
            return await message.answer_audio(res[0], caption=f"🎶 {res[1]}", reply_markup=get_kb(t_id, message.from_user.id, res[1]))

    # ИСПРАВЛЕННЫЙ БАГ С ИМЕНЕМ: берем имя текущего пользователя
    name = message.from_user.first_name if message.from_user.first_name else "пользователь"
    
    welcome = (
        f"Привет, {name}!\n\n"
        f"Я — **Aura Ultimate**, твой музыкальный бот.\n\n"
        f"└  Поиск: Просто напиши название.\n"
        f"└  Shazam: Кидай голосовое.\n"
        f"└  Плейлист: Твои лайки тут /playlist.\n"
        f"└  Кэш: Популярное грузится мгновенно!"
    )
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📂 Мой Плейлист", callback_data="my_playlist")
    await message.answer(welcome, parse_mode=ParseMode.MARKDOWN, reply_markup=kb.as_markup())

@dp.message(F.text & ~F.text.startswith('/'))
async def search(message: types.Message, state: FSMContext):
    if await state.get_state() in [AdState.waiting_for_text, AdState.waiting_for_photo, AdState.waiting_for_link]:
        return

    st = await message.answer("🔎 *Ищу варианты...*", parse_mode=ParseMode.MARKDOWN)
    with YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
        try:
            res = ydl.extract_info(f"ytsearch5:{message.text}", download=False).get('entries', [])
        except Exception as e:
            logger.error(f"Search error: {e}")
            return await st.edit_text("❌ Ошибка поиска.")
    
    if not res: return await st.edit_text("❌ Не найдено.")
    temp_search[message.from_user.id] = res
    kb = InlineKeyboardBuilder()
    for i, r in enumerate(res):
        kb.button(text=f"{i+1}. {r['title'][:40]}", callback_data=f"dl_{i}")
    kb.adjust(1)
    await st.edit_text(f"🔎 Результаты: *{message.text}*", reply_markup=kb.as_markup(), parse_mode=ParseMode.MARKDOWN)

@dp.callback_query(F.data.startswith("dl_"))
async def download(callback: types.CallbackQuery):
    idx = int(callback.data.split("_")[1])
    data = temp_search.get(callback.from_user.id)
    if not data: return await callback.answer("Ошибка сессии.")

    url = data[idx].get('url') or f"https://www.youtube.com/watch?v={data[idx]['id']}"
    cached = conn_m.execute("SELECT track_id, file_id, title FROM cache WHERE original_url = ?", (url,)).fetchone()
    
    if cached:
        await callback.message.delete()
        return await callback.message.answer_audio(cached[1], caption=f"⚡️ Из кэша: {cached[2]}", 
                                                reply_markup=get_kb(cached[0], callback.from_user.id, cached[2]))

    await callback.message.edit_text("📥 *Загрузка...*")
    try:
        path, title, artist = download_track(url)
        audio = types.FSInputFile(path)
        sent = await callback.message.answer_audio(audio, title=title, performer=artist, caption=f"✅ {title}")

        cur = conn_m.cursor()
        cur.execute("INSERT INTO cache (file_id, title, performer, original_url) VALUES (?, ?, ?, ?)", 
                    (sent.audio.file_id, title, artist, url))
        t_id = cur.lastrowid
        conn_m.commit()

        await sent.edit_reply_markup(reply_markup=get_kb(t_id, callback.from_user.id, title))
        if os.path.exists(path): os.remove(path)
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Download error: {e}")
        await callback.message.edit_text(f"❌ Ошибка загрузки.")

@dp.callback_query(F.data == "my_playlist")
async def show_playlist(callback: types.CallbackQuery):
    tracks = conn_m.execute("SELECT c.track_id, c.title FROM cache c JOIN favorites f ON c.track_id = f.track_id WHERE f.user_id = ?", (callback.from_user.id,)).fetchall()
    if not tracks: return await callback.answer("Плейлист пуст!", show_alert=True)
    kb = InlineKeyboardBuilder()
    for t_id, title in tracks: kb.button(text=f"🎵 {title[:40]}", callback_data=f"get_{t_id}")
    kb.adjust(1)
    await callback.message.answer("📂 **Твой Плейлист:**", reply_markup=kb.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("get_"))
async def get_cached(callback: types.CallbackQuery):
    t_id = int(callback.data.split("_")[1])
    res = conn_m.execute("SELECT file_id, title FROM cache WHERE track_id = ?", (t_id,)).fetchone()
    if res: await callback.message.answer_audio(res[0], caption=f"🎶 {res[1]}", reply_markup=get_kb(t_id, callback.from_user.id, res[1]))
    await callback.answer()

@dp.callback_query(F.data.startswith("like_"))
async def like(callback: types.CallbackQuery):
    t_id = int(callback.data.split("_")[1]); u_id = callback.from_user.id
    check = conn_m.execute("SELECT 1 FROM favorites WHERE user_id = ? AND track_id = ?", (u_id, t_id)).fetchone()
    if check: conn_m.execute("DELETE FROM favorites WHERE user_id = ? AND track_id = ?", (u_id, t_id))
    else: conn_m.execute("INSERT INTO favorites VALUES (?, ?)", (u_id, t_id))
    conn_m.commit(); title = conn_m.execute("SELECT title FROM cache WHERE track_id = ?", (t_id,)).fetchone()[0]
    await callback.message.edit_reply_markup(reply_markup=get_kb(t_id, u_id, title)); await callback.answer()

@dp.message(F.voice | F.audio)
async def shazam_detect(message: types.Message, state: FSMContext):
    st = await message.answer("🎧 *Слушаю...*")
    f_id = (message.voice.file_id if message.voice else message.audio.file_id)
    file = await bot.get_file(f_id); path = f"{CACHE_DIR}/{f_id}.ogg"
    await bot.download_file(file.file_path, path); out = await shazam_client.recognize_song(path)
    if os.path.exists(path): os.remove(path)
    if not out.get('track'): return await st.edit_text("❌ Не распознано.")
    title = out['track']['share']['subject']; await st.delete(); message.text = title; await search(message, state)

async def main():
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
