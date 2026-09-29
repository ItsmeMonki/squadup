#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQUADUP — платформа поиска тиммейтов для кооперативных и соревновательных игр.

Бэкенд написан на чистой стандартной библиотеке Python (без внешних зависимостей):
http.server + sqlite3 + json. Раздаёт статику (static/index.html) и REST API.
"""

import json
import os
import random
import re
import sqlite3
import threading
import uuid

import webpush
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# Путь к базе можно переопределить (в облаке указываем том, например /data/squadup.db).
DB_PATH = os.environ.get("DB_PATH") or os.path.join(BASE_DIR, "data.db")
UPLOADS_DIR = os.environ.get("UPLOADS_DIR") or os.path.join(BASE_DIR, "uploads")
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB") or 8)
os.makedirs(UPLOADS_DIR, exist_ok=True)
PORT = int(os.environ.get("PORT", "8000"))
# Демо-данные (88 анкет и 14 сквадов) — только если явно попросили: SQUADUP_DEMO=1.
# По умолчанию база пустая: приложение рассчитано на реальных игроков.
DEMO_DATA = os.environ.get("SQUADUP_DEMO", "").strip().lower() in ("1", "true", "yes", "on")

DB_LOCK = threading.Lock()


# ----------------------------------------------------------------------------
# Каталог игр
# ----------------------------------------------------------------------------

# modes: coop — кооператив/PvE, comp — соревновательные/ранкед, pvp — открытый PvP
# platforms: pc | ps | xbox
GAMES = [
    # --- соревновательные шутеры / киберспорт ---
    dict(id="cs2", name="Counter-Strike 2", short="CS2", genre="Шутер", modes=["comp"], platforms=["pc"],
         ranks=["Silver", "Nova", "Master Guardian", "DMG", "LE", "LEM", "Supreme", "Global Elite", "Faceit 8+"],
         roles=["IGL", "Штурмовик", "AWP-снайпер", "Поддержка", "Люркер", "Тренер"]),
    dict(id="valorant", name="VALORANT", short="VALORANT", genre="Шутер", modes=["comp"], platforms=["pc"],
         ranks=["Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Ascendant", "Immortal", "Radiant"],
         roles=["Дуэлянт", "Инициатор", "Контроллер", "Страж", "IGL"]),
    dict(id="dota2", name="Dota 2", short="Dota 2", genre="MOBA", modes=["comp"], platforms=["pc"],
         ranks=["Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"],
         roles=["Керри", "Мидер", "Оффлейнер", "Саппорт 4", "Саппорт 5", "Капитан"]),
    dict(id="lol", name="League of Legends", short="LoL", genre="MOBA", modes=["comp"], platforms=["pc"],
         ranks=["Iron", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Master", "Challenger"],
         roles=["Топ", "Лес", "Мид", "ADC", "Поддержка"]),
    dict(id="apex", name="Apex Legends", short="Apex", genre="Шутер", modes=["comp", "coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Rookie", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Predator"],
         roles=["Фраггер", "Скаут", "Поддержка", "IGL"]),
    dict(id="ow2", name="Overwatch 2", short="OW2", genre="Шутер", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Grandmaster", "Top 500"],
         roles=["Танк", "ДПС", "Саппорт"]),
    dict(id="r6", name="Rainbow Six Siege", short="R6 Siege", genre="Шутер", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Copper", "Bronze", "Silver", "Gold", "Platinum", "Emerald", "Diamond", "Champion"],
         roles=["Фраггер", "Анкор", "Роумер", "Сапорт", "IGL"]),
    dict(id="cod", name="Call of Duty", short="CoD", genre="Шутер", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Crimson", "Iridescent", "Top 250"],
         roles=["Ассаулт", "Снайпер", "Поддержка", "IGL"]),
    dict(id="marvel_rivals", name="Marvel Rivals", short="Rivals", genre="Шутер", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Grandmaster", "Celestial", "Eternity"],
         roles=["Вангард", "Дуэлянт", "Стратег"]),
    dict(id="fortnite", name="Fortnite", short="Fortnite", genre="Battle Royale", modes=["comp", "coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Elite", "Champion", "Unreal"],
         roles=["Фраггер", "Строитель", "Сапорт", "IGL"]),
    dict(id="pubg", name="PUBG: Battlegrounds", short="PUBG", genre="Battle Royale", modes=["comp", "coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Бронза", "Серебро", "Золото", "Платина", "Алмаз", "Мастер", "Топ-500"],
         roles=["Ассаулт", "Снайпер", "Медик", "Водитель", "IGL"]),
    dict(id="rl", name="Rocket League", short="Rocket League", genre="Спорт", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Champion", "GC", "SSL"],
         roles=["Нападающий", "Полузащитник", "Защитник", "Вратарь"]),
    dict(id="bf6", name="Battlefield 6", short="BF6", genre="Шутер", modes=["comp", "coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Рядовой", "Сержант", "Лейтенант", "Полковник"],
         roles=["Штурмовик", "Инженер", "Медик", "Разведка", "Пилот"]),
    dict(id="deadlock", name="Deadlock", short="Deadlock", genre="MOBA-шутер", modes=["comp"], platforms=["pc"],
         ranks=["Новичок", "Archon", "Oracle", "Phantom", "Eternus"],
         roles=["Керри", "Ганкер", "Танк", "Сапорт"]),
    dict(id="eafc", name="EA SPORTS FC", short="EA FC", genre="Спорт", modes=["comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Div 10", "Div 7", "Div 5", "Div 3", "Div 1", "Elite"],
         roles=["Любая позиция", "Атака", "Полузащита", "Защита", "Вратарь"]),
    # --- кооператив / PvE ---
    dict(id="hd2", name="Helldivers 2", short="Helldivers 2", genre="Кооп-шутер", modes=["coop"],
         platforms=["pc", "ps"],
         ranks=["Кадет", "Сержант", "Старшип", "Коммандер", "Адмирал", "Hell Dive"],
         roles=["Анти-танк", "Стрелок", "Поддержка", "Разведка", "Пилот"]),
    dict(id="arc_raiders", name="ARC Raiders", short="ARC Raiders", genre="Extraction-шутер",
         modes=["coop"], platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Рейдер", "Ветеран", "Элита"],
         roles=["Штурмовик", "Инженер", "Медик", "Скаут"]),
    dict(id="tarkov", name="Escape from Tarkov", short="Tarkov", genre="Extraction-шутер",
         modes=["coop"], platforms=["pc"],
         ranks=["Новичок", "Уровень 15+", "Уровень 30+", "Уровень 45+", "Хардкор"],
         roles=["Штурмовик", "Снайпер", "Медик", "Рейдер"]),
    dict(id="delta", name="Delta Force", short="Delta Force", genre="Шутер", modes=["comp", "coop"],
         platforms=["pc"],
         ranks=["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master"],
         roles=["Штурмовик", "Медик", "Инженер", "Скаут"]),
    dict(id="drg", name="Deep Rock Galactic", short="DRG", genre="Кооп-шутер", modes=["coop"],
         platforms=["pc", "xbox", "ps"],
         ranks=["Зелёный бородач", "Бородач", "Седобородый", "Легендарный"],
         roles=["Скаут", "Инженер", "Бурильщик", "Стрелок"]),
    dict(id="pd3", name="PAYDAY 3", short="PAYDAY 3", genre="Кооп-шутер", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Профи", "Убийца", "Легенда"],
         roles=["Стелс", "Штурм", "Техник", "Переговорщик"]),
    dict(id="destiny2", name="Destiny 2", short="Destiny 2", genre="Looter-shooter", modes=["coop", "comp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Стражник", "Легенда", "Рейд-хардкор"],
         roles=["Титан", "Охотник", "Варлок"]),
    dict(id="warframe", name="Warframe", short="Warframe", genre="Looter-shooter", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "MR 10+", "MR 20+", "MR 30+"],
         roles=["DPS", "Поддержка", "Контроль", "Спасатель"]),
    dict(id="division2", name="The Division 2", short="Division 2", genre="Looter-shooter",
         modes=["coop", "comp"], platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Уровень 40", "SHD 100+", "SHD 500+"],
         roles=["DPS", "Танк", "Хилер", "Скилл"]),
    dict(id="lethal", name="Lethal Company", short="Lethal Co.", genre="Хоррор-кооп", modes=["coop"],
         platforms=["pc"],
         ranks=["Стажёр", "Сотрудник", "Старший сотрудник", "Легенда компании"],
         roles=["Сканер", "Сборщик", "Носильщик", "Связист"]),
    dict(id="phasmo", name="Phasmophobia", short="Phasmophobia", genre="Хоррор-кооп", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Опытный", "Профи", "Эксперт", "Ночной кошмар"],
         roles=["Исследователь", "Фотограф", "Оператор", "Скептик"]),
    dict(id="sot", name="Sea of Thieves", short="Sea of Thieves", genre="Приключение",
         modes=["coop", "pvp"], platforms=["pc", "ps", "xbox"],
         ranks=["Матрос", "Старпом", "Капитан", "Легенда Воров"],
         roles=["Рулевой", "Канонир", "Такелажник", "Кок"]),
    dict(id="bg3", name="Baldur's Gate 3", short="BG3", genre="RPG", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Акт I", "Акт II", "Акт III", "Хардкор"],
         roles=["Танк", "Хилер", "Маг", "Разбойник", "Бард"]),
    dict(id="mhw", name="Monster Hunter Wilds", short="MH Wilds", genre="Экшн-RPG", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Охотник", "Мастер рангов", "HR 100+"],
         roles=["Мечник", "Стрелок", "Поддержка", "Танк"]),
    dict(id="minecraft", name="Minecraft", short="Minecraft", genre="Песочница", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Строитель", "Редстоун-инженер", "Ветеран"],
         roles=["Строитель", "Фарм", "PVP", "Исследователь"]),
    dict(id="valheim", name="Valheim", short="Valheim", genre="Выживание", modes=["coop"], platforms=["pc"],
         ranks=["Новичок", "Воин", "Ветеран", "Убийца боссов"],
         roles=["Воин", "Лучник", "Маг", "Строитель"]),
    dict(id="palworld", name="Palworld", short="Palworld", genre="Выживание", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Тренер", "Мастер", "Легенда"],
         roles=["Фарм", "Бой", "Строитель", "Исследователь"]),
    dict(id="terraria", name="Terraria", short="Terraria", genre="Песочница", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Хардмод", "Планиум", "Эксперт"],
         roles=["Воин", "Маг", "Стрелок", "Призыватель"]),
    dict(id="enshrouded", name="Enshrouded", short="Enshrouded", genre="Выживание", modes=["coop"],
         platforms=["pc"],
         ranks=["Новичок", "Искатель", "Ветеран", "Мастер"],
         roles=["Воин", "Маг", "Стрелок", "Строитель"]),
    dict(id="itt", name="It Takes Two", short="It Takes Two", genre="Кооп-приключение", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Прошли главу", "Прошли игру"],
         roles=["Мэй", "Коди"]),
    dict(id="rust", name="Rust", short="Rust", genre="Выживание", modes=["coop", "pvp"], platforms=["pc"],
         ranks=["Новичок", "Фермер", "Рейдер", "Полный вайп"],
         roles=["Фарм", "Рейд", "PVP", "Строитель", "Электрик"]),
    dict(id="gta", name="GTA Online", short="GTA Online", genre="Экшн", modes=["coop", "pvp"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "Уровень 50+", "Уровень 120+", "Уровень 250+"],
         roles=["Миссии", "Хейсты", "Гонки", "Свободный режим"]),
    dict(id="wow", name="World of Warcraft", short="WoW", genre="MMORPG", modes=["coop", "comp"],
         platforms=["pc"],
         ranks=["Новичок", "Ключи +10", "Мифик-рейд", "Хардкор"],
         roles=["Танк", "Хилер", "DPS", "Рейд-лид"]),
    dict(id="ffxiv", name="Final Fantasy XIV", short="FFXIV", genre="MMORPG", modes=["coop"],
         platforms=["pc", "ps", "xbox"],
         ranks=["Новичок", "AR 30+", "Савейдж-рейд", "Легенда"],
         roles=["Танк", "Хилер", "DPS"]),
    dict(id="albion", name="Albion Online", short="Albion", genre="MMORPG", modes=["coop", "pvp"],
         platforms=["pc"],
         ranks=["Новичок", "T5", "T7", "T8"],
         roles=["Танк", "Хилер", "DPS", "Сапорт"]),
]

GAME_BY_ID = {g["id"]: g for g in GAMES}

# --- Discord OAuth (необязательно: включается переменными окружения) ---
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "").strip()
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "").strip()
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "").strip()  # если пусто — соберём из запроса
DISCORD_ENABLED = bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET)

# --- Steam: вход только через официальный OpenID 2.0 (steamcommunity.com) ---
# Пароль Steam пользователь вводит только на сайте Steam: мы его не видим и не храним.
# Ключ Steam Web API не нужен: ник и аватар берём из публичного XML-профиля.
STEAM_OPENID_ENDPOINT = os.environ.get("STEAM_OPENID_ENDPOINT",
                                       "https://steamcommunity.com/openid/login").strip()
STEAM_PROFILE_XML = os.environ.get("STEAM_PROFILE_XML",
                                   "https://steamcommunity.com/profiles/{}/?xml=1").strip()
STEAM_CLAIMED_ID_RE = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{17})$")

OAUTH_STATES = {}          # state -> {"created": datetime, "link_uid": uid | None}
OAUTH_LOCK = threading.Lock()

PLATFORM_LABELS = {"pc": "PC", "ps": "PlayStation", "xbox": "Xbox"}
MODE_LABELS = {"coop": "Кооператив", "comp": "Соревновательный", "pvp": "PvP"}
REGIONS = [
    dict(id="ru", label="Россия"),
    dict(id="cis", label="СНГ"),
    dict(id="kz", label="Казахстан"),
    dict(id="by", label="Беларусь"),
    dict(id="ua", label="Украина"),
    dict(id="de", label="Германия"),
    dict(id="pl", label="Польша"),
    dict(id="eu", label="Европа"),
]
REGION_BY_ID = {r["id"]: r for r in REGIONS}

SKILL_LABELS = {1: "Новичок", 2: "Любитель", 3: "Средний", 4: "Продвинутый", 5: "Про"}

VIBES = {
    "serious": "Серьёзная игра",
    "chill": "По кайфу",
    "learning": "Учусь игре",
    "tournament": "Турниры и лиги",
}

SCHEDULE_SLOTS = ["Утро 6–12", "День 12–18", "Вечер 18–24", "Ночь 0–6", "Выходные"]

LANGUAGES = ["Русский", "English", "Deutsch", "Українська", "Polski", "Қазақша"]


# ----------------------------------------------------------------------------
# База данных
# ----------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    token TEXT UNIQUE,
    nickname TEXT,
    created_at TEXT,
    password_hash TEXT
);
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    nick TEXT,
    age INTEGER,
    region TEXT,
    platforms TEXT,
    languages TEXT,
    skill INTEGER,
    mic INTEGER,
    vibe TEXT,
    schedule TEXT,
    about TEXT,
    games TEXT,
    rating REAL,
    reviews_count INTEGER,
    hours INTEGER,
    online INTEGER,
    verified INTEGER,
    last_seen TEXT,
    reviews TEXT,
    is_seed INTEGER DEFAULT 1,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    listing_id INTEGER,
    peer_nick TEXT,
    unread INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    sender TEXT,
    text TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS squads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    tag TEXT,
    game_id TEXT,
    mode TEXT,
    region TEXT,
    language TEXT,
    size INTEGER,
    filled INTEGER,
    need TEXT,
    min_rank TEXT,
    mic INTEGER,
    schedule TEXT,
    about TEXT,
    captain TEXT,
    owner_id TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    squad_id INTEGER,
    user_id TEXT,
    message TEXT,
    status TEXT DEFAULT 'sent',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id TEXT, reporter_nick TEXT, target_type TEXT, target_id INTEGER,
    target_nick TEXT, reason TEXT, comment TEXT, status TEXT DEFAULT 'new', created_at TEXT
);
CREATE TABLE IF NOT EXISTS blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT, blocked_user_id TEXT, blocked_nick TEXT, created_at TEXT,
    UNIQUE(user_id, blocked_user_id)
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    endpoint TEXT UNIQUE,
    p256dh TEXT,
    auth TEXT,
    user_agent TEXT,
    created_at TEXT,
    last_ok TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS player_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER,
    user_id TEXT,
    author TEXT,
    rating INTEGER,
    text TEXT,
    created_at TEXT,
    UNIQUE(listing_id, user_id)
);
"""


def now_iso(offset_minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.replace(microsecond=0).isoformat()


def iso_cutoff(minutes):
    """ISO-метка N минут назад (для окон «ищу сейчас»)."""
    return now_iso(-minutes)


LOOKING_WINDOW_MIN = 90

# --- Web Push (уведомления) ---
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@squadup.app")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
PUSH_ENABLED = webpush.CRYPTO_AVAILABLE


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()


def vapid_keys(conn):
    """Возвращает (public, private): переменные окружения, затем БД, затем сгенерировать и сохранить."""
    global VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY
    if VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY:
        return VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY
    pub, priv = get_setting(conn, "vapid_public"), get_setting(conn, "vapid_private")
    if not (pub and priv):
        if not PUSH_ENABLED:
            return "", ""
        pub, priv = webpush.generate_vapid_keys()
        set_setting(conn, "vapid_public", pub)
        set_setting(conn, "vapid_private", priv)
        print("[push] сгенерирована VAPID-пара ключей (сохранена в базе)", flush=True)
    VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY = pub, priv
    return pub, priv


def push_to_user(conn, user_id, payload):
    """Отправляет push всем устройствам пользователя. Возвращает (sent, removed)."""
    if not user_id or not PUSH_ENABLED:
        return 0, 0
    pub, priv = vapid_keys(conn)
    if not (pub and priv):
        return 0, 0
    rows = conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchall()
    if not rows:
        return 0, 0
    sent = removed = 0
    for r in rows:
        ok, status, err = webpush.send_web_push(
            {"endpoint": r["endpoint"], "p256dh": r["p256dh"], "auth": r["auth"]},
            payload, pub, priv, VAPID_SUBJECT)
        if ok:
            sent += 1
            conn.execute("UPDATE push_subscriptions SET last_ok = ? WHERE id = ?", (now_iso(), r["id"]))
        elif status in (404, 410):
            conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (r["id"],))
            removed += 1
        else:
            print(f"[push] ошибка отправки ({status}): {err}", flush=True)
    conn.commit()
    return sent, removed


def push_async(user_id, payload):
    """Отправка в фоне: не блокируем ответ клиенту сетью push-сервиса."""
    def worker():
        conn = db_connect()
        try:
            push_to_user(conn, user_id, payload)
        except Exception as exc:  # noqa: BLE001
            print("[push] фоновая ошибка:", exc, flush=True)
        finally:
            conn.close()
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Чаты между аккаунтами, блокировки, модерация
# ---------------------------------------------------------------------------
# Внутренняя договорённость по таблице messages: sender = 'me' — это всегда
# автор-инициатор чата (chats.user_id), sender = 'peer' — второй участник.
# Клиенту отдаём роли уже пересчитанными относительно того, кто смотрит диалог.

MODERATION_HIDE_THRESHOLD = 3   # столько жалоб автоматически скрывает анкету из поиска
REPORT_REASONS = {
    "spam": "Спам или реклама",
    "insult": "Оскорбления, токсичность",
    "fake": "Фейковая анкета / чужой ник",
    "fraud": "Мошенничество, обман",
    "adult": "Неприемлемый контент",
    "other": "Другое",
}


def qint(query, name, default=0, lo=None, hi=None):
    """Безопасно достаём целое из query-параметров: мусор не должен ронять запрос в 500."""
    raw = (query.get(name) or [None])[0]
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val


def peer_presence(conn, peer_uid, listing_id):
    """Онлайн-статус, время последнего визита и аватар собеседника.

    Для реального игрока берём его анкету (онлайн + аватар из Steam, если игрок
    разрешил показывать профиль). Для гостевой анкеты без аккаунта — саму анкету.
    """
    row = None
    if peer_uid:
        row = conn.execute("SELECT online, last_seen, user_id FROM listings WHERE user_id = ?",
                           (peer_uid,)).fetchone()
    if row is None and listing_id:
        row = conn.execute("SELECT online, last_seen, user_id FROM listings WHERE id = ?",
                           (listing_id,)).fetchone()
    if row is None:
        return False, None, ""
    avatar = ""
    if row["user_id"]:
        su = conn.execute("SELECT steam_id, steam_avatar, steam_public FROM users WHERE id = ?",
                          (row["user_id"],)).fetchone()
        if su and su["steam_id"] and (su["steam_public"] is None or su["steam_public"]):
            avatar = su["steam_avatar"] or ""
    return bool(row["online"]), row["last_seen"], avatar


def chat_partner(conn, c, uid):
    """По uid возвращает (peer_user_id, peer_nick, я_инициатор, мои_непрочитанные)."""
    is_initiator = (c["user_id"] == uid)
    if is_initiator:
        peer_uid = c["peer_user_id"] if "peer_user_id" in c.keys() else None
        return peer_uid, c["peer_nick"], True, c["unread"]
    other = conn.execute("SELECT nickname FROM users WHERE id = ?", (c["user_id"],)).fetchone()
    unread_b = c["unread_b"] if "unread_b" in c.keys() else 0
    return c["user_id"], (other["nickname"] if other else "Игрок"), False, unread_b


def user_display(conn, uid, fallback="Игрок"):
    if not uid:
        return fallback
    row = conn.execute("SELECT nickname FROM users WHERE id = ?", (uid,)).fetchone()
    return row["nickname"] if row else fallback


def blocked_ids(conn, uid):
    """Множество аккаунтов, с которыми у меня блокировка в любую сторону."""
    if not uid:
        return set()
    rows = conn.execute(
        "SELECT blocked_user_id AS x FROM blocks WHERE user_id = ? "
        "UNION SELECT user_id AS x FROM blocks WHERE blocked_user_id = ?", (uid, uid)).fetchall()
    return {r["x"] for r in rows if r["x"]}


def is_blocked_between(conn, a, b):
    if not a or not b:
        return False
    row = conn.execute(
        "SELECT 1 FROM blocks WHERE (user_id = ? AND blocked_user_id = ?) "
        "OR (user_id = ? AND blocked_user_id = ?)", (a, b, b, a)).fetchone()
    return bool(row)


def find_chat(conn, a, b):
    """Диалог между двумя аккаунтами — в любом направлении."""
    return conn.execute(
        "SELECT * FROM chats WHERE (user_id = ? AND peer_user_id = ?) "
        "OR (user_id = ? AND peer_user_id = ?)", (a, b, b, a)).fetchone()


def unread_count(conn, user_id):
    """Непрочитанные в личных диалогах (запросы на переписку в счётчик не идут)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN user_id = ? THEN unread ELSE unread_b END), 0) AS u "
        "FROM chats WHERE (user_id = ? OR peer_user_id = ?) AND COALESCE(requested, 0) = 0",
        (user_id, user_id, user_id)).fetchone()
    return row["u"] if row else 0


# ---------- игровой статус: что делает игрок прямо сейчас ----------
PRESENCE_LABELS = {
    "offline": "офлайн",
    "online": "онлайн",
    "looking": "ищу тиммейтов",
    "lobby": "в пати",
    "playing": "играет",
}


def touch_presence(conn, uid):
    """Отмечаем, что игрок только что был в сети (онлайн живёт 2 минуты)."""
    if not uid:
        return
    stamp = now_iso()
    conn.execute("UPDATE users SET online = 1, last_seen = ? WHERE id = ?", (stamp, uid))
    conn.execute("UPDATE listings SET online = 1, last_seen = ? WHERE user_id = ?", (stamp, uid))


def user_presence(conn, uid):
    """Игровой статус игрока: офлайн / онлайн / ищу тиммейтов / в пати / играет."""
    out = dict(state="offline", label=PRESENCE_LABELS["offline"], game_id=None, game_name=None,
               game_short=None, mode=None, party_id=None, party_status=None, players=None, size=None,
               looking=False, avatar="", nick="")
    if not uid:
        return out
    u = conn.execute("SELECT nickname FROM users WHERE id = ?", (uid,)).fetchone()
    out["nick"] = u["nickname"] if u else ""
    row = conn.execute("SELECT online, last_seen, looking_at FROM listings WHERE user_id = ?",
                       (uid,)).fetchone()
    seen = None
    if row and row["last_seen"]:
        seen = row["last_seen"]
    urow = conn.execute("SELECT last_seen FROM users WHERE id = ?", (uid,)).fetchone()
    if urow and urow["last_seen"] and (not seen or urow["last_seen"] > seen):
        seen = urow["last_seen"]
    fresh = bool(seen and seen >= iso_cutoff(2))
    out["state"] = "online" if fresh else "offline"
    out["label"] = PRESENCE_LABELS[out["state"]]
    if row and row["looking_at"] and row["looking_at"] >= iso_cutoff(LOOKING_WINDOW_MIN):
        out["looking"] = True
    # пати важнее: если игрок в составе — показываем игру и состав
    p = conn.execute(
        """SELECT p.* FROM parties p JOIN group_members m ON m.chat_id = p.chat_id
           WHERE m.user_id = ? AND p.status IN ('open', 'playing') ORDER BY p.id DESC LIMIT 1""",
        (uid,)).fetchone()
    if p:
        out["party_id"] = p["id"]
        out["party_status"] = p["status"]
        out["game_id"] = p["game_id"]
        g = GAME_BY_ID.get(p["game_id"])
        if g:
            out["game_name"] = g["name"]
            out["game_short"] = g["short"]
        out["mode"] = MODE_LABELS.get(p["mode"], p["mode"])
        cnt = conn.execute("SELECT COUNT(*) AS c FROM group_members WHERE chat_id = ?",
                           (p["chat_id"],)).fetchone()["c"]
        out["players"], out["size"] = cnt, p["size"]
        if out["state"] == "online":
            out["state"] = "playing" if p["status"] == "playing" else "lobby"
            out["label"] = PRESENCE_LABELS[out["state"]]
        return out
    if out["state"] == "online" and out["looking"]:
        out["state"], out["label"] = "looking", PRESENCE_LABELS["looking"]
    # аватар: Steam, если привязан и разрешён
    su = conn.execute("SELECT steam_id, steam_avatar, steam_public FROM users WHERE id = ?", (uid,)).fetchone()
    if su and su["steam_id"] and (su["steam_public"] is None or su["steam_public"]):
        out["avatar"] = su["steam_avatar"] or ""
    return out


def presence_line(p):
    """Короткая строка статуса для списка чатов и карточек."""
    if p["state"] == "playing" and p["game_name"]:
        return f"Играет: {p['game_name']}"
    if p["state"] == "lobby" and p["game_name"]:
        return f"В пати: {p['game_name']} {p['players']}/{p['size']}"
    if p["state"] == "looking":
        return "Ищет тиммейтов"
    if p["state"] == "online":
        return "Онлайн"
    return "Не в сети"


def parse_multipart(body, boundary):
    """Разбор multipart/form-data без внешних библиотек (у нас только стандартная)."""
    out = {}
    if not boundary:
        return out
    delim = b"--" + boundary.encode()
    for part in body.split(delim)[1:]:
        if part[:2] == b"--":
            break
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name = filename = None
        ctype = "application/octet-stream"
        for line in head.decode("utf-8", "replace").split("\r\n"):
            low = line.lower()
            if low.startswith("content-disposition"):
                for kv in line.split(";")[1:]:
                    k, _, v = kv.strip().partition("=")
                    v = v.strip().strip('"')
                    if k == "name":
                        name = v
                    elif k == "filename":
                        filename = v
            elif low.startswith("content-type"):
                ctype = line.split(":", 1)[1].strip()
        if name:
            out[name] = dict(filename=filename, ctype=ctype, data=data)
    return out


def safe_filename(name):
    name = os.path.basename(name or "file")
    name = re.sub(r"[^A-Za-zА-Яа-я0-9._-]+", "_", name)[:80] or "file"
    return name


def extract_mentions(conn, chat_id, text):
    """Упоминания @ник внутри группового чата: только участники этой группы."""
    found = []
    for token in re.findall(r"@([A-Za-zА-Яа-я0-9_]{2,32})", text or ""):
        row = conn.execute(
            "SELECT u.id, u.nickname FROM users u JOIN group_members m ON m.user_id = u.id "
            "WHERE m.chat_id = ? AND u.nickname = ? COLLATE NOCASE", (chat_id, token)).fetchone()
        if row and not any(x["user_id"] == row["id"] for x in found):
            found.append(dict(nick=row["nickname"], user_id=row["id"]))
    return found


def poll_expired(meta):
    dl = (meta or {}).get("deadline")
    return bool(dl and dl < now_iso())


def player_tags(conn, listing):
    """Словами, без значков: короткие метки игрока для карточки."""
    tags = []
    if listing["mic"]:
        tags.append("С микрофоном")
    if (listing["rating"] or 0) >= 4.5 and (listing["reviews_count"] or 0) >= 3:
        tags.append("Надёжный тиммейт")
    if (listing["reviews_count"] or 0) >= 5:
        tags.append("Опытный в составе")
    vibe = VIBES.get(listing["vibe"], "")
    if vibe:
        tags.append("Настрой: " + vibe.lower())
    if listing["verified"]:
        tags.append("Steam подтверждён")
    sched = json.loads(listing["schedule"] or "[]")
    if any("Вечер" in x for x in sched):
        tags.append("Играет вечерами")
    if any("Ночь" in x for x in sched):
        tags.append("Играет ночью")
    return tags[:5]


def resolve_user_key(conn, key):
    """По нику или id находим аккаунт — удобно и для ссылок, и для списков."""
    key = (key or "").strip()[:64]
    if not key:
        return ""
    row = conn.execute("SELECT id FROM users WHERE id = ?", (key,)).fetchone()
    if row:
        return row["id"]
    row = conn.execute("SELECT id FROM users WHERE nickname = ? COLLATE NOCASE", (key,)).fetchone()
    return row["id"] if row else ""


def user_card(conn, uid):
    """Компактная карточка игрока для чата: ник, аватар, статус, ссылка на анкету."""
    p = user_presence(conn, uid)
    row = conn.execute("SELECT id, nick FROM listings WHERE user_id = ? ORDER BY id LIMIT 1", (uid,)).fetchone()
    p["listing_id"] = row["id"] if row else None
    p["nick"] = p["nick"] or (row["nick"] if row else "Игрок")
    return p


def group_member_ids(conn, chat_id):
    return [r["user_id"] for r in conn.execute(
        "SELECT user_id FROM group_members WHERE chat_id = ?", (chat_id,)).fetchall()]


def in_group(conn, chat_id, uid):
    return bool(uid and conn.execute("SELECT 1 FROM group_members WHERE chat_id = ? AND user_id = ?",
                                     (chat_id, uid)).fetchone())


def group_unread(conn, chat_id, uid):
    m = conn.execute("SELECT last_read_at FROM group_members WHERE chat_id = ? AND user_id = ?",
                     (chat_id, uid)).fetchone()
    since = (m["last_read_at"] if m else None) or ""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM group_messages WHERE chat_id = ? AND user_id != ? AND deleted = 0 "
        "AND created_at > ?", (chat_id, uid, since)).fetchone()
    return row["c"] if row else 0


def unread_groups_total(conn, uid):
    rows = conn.execute("SELECT chat_id FROM group_members WHERE user_id = ?", (uid,)).fetchall()
    return sum(group_unread(conn, r["chat_id"], uid) for r in rows)


def group_title(conn, g):
    if g["title"]:
        return g["title"]
    gid = g["game_id"]
    gg = GAME_BY_ID.get(gid) if gid else None
    return (gg["name"] if gg else "Группа")


def party_brief(conn, party_id, uid=None):
    """Пати целиком: игра, состав со статусами и готовностью, лидер."""
    p = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
    if not p:
        return None
    g = GAME_BY_ID.get(p["game_id"]) if p["game_id"] else None
    members = []
    for m in conn.execute("SELECT * FROM group_members WHERE chat_id = ? ORDER BY joined_at", (p["chat_id"],)):
        card = user_card(conn, m["user_id"])
        card.update(dict(last_read_at=(m["last_read_at"] if "last_read_at" in m.keys() else None),
                         user_id=m["user_id"], ready=bool(m["ready"]), role=m["role"],
                         is_leader=(m["user_id"] == p["leader_user_id"]),
                         is_me=(m["user_id"] == uid)))
        members.append(card)
    return dict(
        id=p["id"], chat_id=p["chat_id"], game_id=p["game_id"],
        game_name=(g["name"] if g else ""), game_short=(g["short"] if g else ""),
        mode=p["mode"], region=p["region"], rank=p["rank"], mic=bool(p["mic"]), lang=p["lang"],
        size=p["size"], note=p["note"], status=p["status"], leader_user_id=p["leader_user_id"],
        players=len(members), members=members,
        is_member=bool(uid and any(m["user_id"] == uid for m in members)),
        is_leader=bool(uid and uid == p["leader_user_id"]),
        created_at=p["created_at"],
    )


def add_system_message(conn, chat_id, text, meta=None):
    conn.execute(
        "INSERT INTO group_messages (chat_id, user_id, text, kind, meta, created_at) VALUES (?,?,?,?,?,?)",
        (chat_id, None, text, "system", json.dumps(meta or {}, ensure_ascii=False), now_iso()))


def create_party(conn, uid, game_id, mode="", region="", rank="", mic=0, size=5, lang="", note=""):
    """Пати = групповой чат + состав + игровой контекст в шапке."""
    cur = conn.execute(
        """INSERT INTO group_chats (kind, title, game_id, mode, region, rank, created_at, updated_at)
           VALUES ('party', ?, ?, ?, ?, ?, ?, ?)""",
        ("", game_id, mode, region, rank, now_iso(), now_iso()))
    chat_id = cur.lastrowid
    cur = conn.execute(
        """INSERT INTO parties (chat_id, game_id, mode, region, rank, mic, lang, size, note,
                                leader_user_id, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,'open',?,?)""",
        (chat_id, game_id, mode, region, rank, int(bool(mic)), lang, size, note, uid, now_iso(), now_iso()))
    party_id = cur.lastrowid
    conn.execute("UPDATE group_chats SET party_id = ? WHERE id = ?", (party_id, chat_id))
    conn.execute("INSERT INTO group_members (chat_id, user_id, joined_at, last_read_at, role) VALUES (?,?,?,?, 'leader')",
                 (chat_id, uid, now_iso(), now_iso()))
    gg = GAME_BY_ID.get(game_id)
    title = (gg["name"] if gg else "Пати")
    conn.execute("UPDATE group_chats SET title = ? WHERE id = ?", (f"Пати · {title}", chat_id))
    add_system_message(conn, chat_id, f"Пати собрано: {title}"
                        + (f" · {MODE_LABELS.get(mode, mode)}" if mode else "")
                        + f" · нужно {size} игроков")
    conn.commit()
    return party_id, chat_id


def pb_game_name(conn, party_row):
    g = GAME_BY_ID.get(party_row["game_id"])
    return g["name"] if g else "Игра"


def close_session(conn, party_id):
    """Закрываем сессию пати: считаем минуты, чтобы потом предложить «играть снова»."""
    r = conn.execute("SELECT * FROM party_sessions WHERE party_id = ? AND ended_at IS NULL "
                     "ORDER BY id DESC LIMIT 1", (party_id,)).fetchone()
    if not r:
        return None
    try:
        t0 = datetime.fromisoformat(r["started_at"])
        minutes = max(1, int((datetime.now(timezone.utc) - t0).total_seconds() // 60))
    except Exception:
        minutes = 0
    conn.execute("UPDATE party_sessions SET ended_at = ?, minutes = ? WHERE id = ?", (now_iso(), minutes, r["id"]))
    return dict(id=r["id"], minutes=minutes, game_id=r["game_id"])


def post_card(conn, chat_id, uid, kind, meta, text=""):
    cur = conn.execute(
        "INSERT INTO group_messages (chat_id, user_id, text, kind, meta, created_at) VALUES (?,?,?,?,?,?)",
        (chat_id, uid, text, kind, json.dumps(meta, ensure_ascii=False), now_iso()))
    return cur.lastrowid


def toggle_reaction(conn, chat_kind, chat_id, message_id, uid, value):
    value = (value or "").strip()[:16]
    if value not in REACTIONS_ALLOWED:
        return None
    row = conn.execute("SELECT 1 FROM reactions WHERE chat_kind = ? AND chat_id = ? AND message_id = ? "
                       "AND user_id = ? AND value = ?", (chat_kind, chat_id, message_id, uid, value)).fetchone()
    if row:
        conn.execute("DELETE FROM reactions WHERE chat_kind = ? AND chat_id = ? AND message_id = ? "
                     "AND user_id = ? AND value = ?", (chat_kind, chat_id, message_id, uid, value))
        return False
    conn.execute("INSERT INTO reactions (chat_kind, chat_id, message_id, user_id, value, created_at) "
                 "VALUES (?,?,?,?,?,?)", (chat_kind, chat_id, message_id, uid, value, now_iso()))
    return True


REACTIONS_ALLOWED = ["Го", "Жду", "Круто", "Смешно", "Мимо", "Плюс"]


def poll_state(conn, chat_kind, chat_id, message_id, meta, uid):
    """Опрос: варианты, голоса, мой выбор (одним или несколькими)."""
    options = meta.get("options") or []
    rows = conn.execute("SELECT choice, user_id FROM poll_votes WHERE chat_kind = ? AND chat_id = ? "
                        "AND message_id = ?", (chat_kind, chat_id, message_id)).fetchall()
    votes = [0] * len(options)
    mine = None
    voters = [[] for _ in options]
    for r in rows:
        if 0 <= r["choice"] < len(options):
            votes[r["choice"]] += 1
            voters[r["choice"]].append(user_display(conn, r["user_id"]))
        if r["user_id"] == uid:
            mine = r["choice"]
    return dict(question=meta.get("question") or "Опрос", options=options, votes=votes,
                voters=voters, my_choice=mine, total=len(rows),
                multi=bool(meta.get("multi")), deadline=meta.get("deadline"),
                expired=poll_expired(meta))


def group_item(conn, r, uid, quotes=None, reacts=None, chat_kind="group", chat_id=None):
    """Сообщение группового чата в том же виде, что и личные: sender — 'me' или ник."""
    meta = {}
    if r["meta"]:
        try:
            meta = json.loads(r["meta"])
        except Exception:
            meta = {}
    sender = "me" if r["user_id"] == uid else "peer"
    card = user_card(conn, r["user_id"]) if r["user_id"] else None
    quote = None
    if r["reply_to"] and quotes is not None:
        q = quotes.get(r["reply_to"])
        if q is not None:
            q_card = user_card(conn, q["user_id"]) if q["user_id"] else None
            quote = dict(id=q["id"], nick=(q_card["nick"] if q_card else "Система"),
                         text=("Сообщение удалено" if q["deleted"] else (q["text"] or ""))[:160])
    item = dict(
        id=r["id"], sender=sender, text="" if r["deleted"] else (r["text"] or ""),
        created_at=r["created_at"], deleted=bool(r["deleted"]), edited=bool(r["edited_at"]),
        kind=r["kind"] or "text", meta=meta, reply_to=quote, pinned=bool(r["pinned"]),
        nick=(card["nick"] if card else "Система"), avatar=(card["avatar"] if card else ""),
        user_id=(r["user_id"] or ""), presence=(card["state"] if card else None),
        reactions=(reacts or {}).get(r["id"], []),
    )
    if item["kind"] == "poll" and not item["deleted"]:
        item["poll"] = poll_state(conn, chat_kind, chat_id or r["chat_id"], r["id"], meta, uid)
    if item["kind"] == "lfg" and meta.get("party_id"):
        pb = party_brief(conn, meta["party_id"], uid)
        if pb:
            item["party"] = dict(id=pb["id"], players=pb["players"], size=pb["size"], status=pb["status"],
                                 is_member=pb["is_member"])
    return item


def dm_unread_total(conn, uid):
    return unread_count(conn, uid)


def migrate(conn):
    """Догоняем схему для баз, созданных предыдущими версиями."""
    # --- игровой слой чата: пати, групповые чаты, реакции (1.9) ---
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS parties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        game_id TEXT,
        mode TEXT,
        region TEXT,
        rank TEXT,
        mic INTEGER DEFAULT 0,
        lang TEXT,
        size INTEGER DEFAULT 5,
        note TEXT,
        leader_user_id TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT,
        updated_at TEXT,
        closed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS group_chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT DEFAULT 'group',
        title TEXT,
        game_id TEXT,
        mode TEXT,
        region TEXT,
        rank TEXT,
        party_id INTEGER,
        created_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS group_members (
        chat_id INTEGER,
        user_id TEXT,
        joined_at TEXT,
        last_read_at TEXT,
        ready INTEGER DEFAULT 0,
        role TEXT DEFAULT 'member',
        muted_until TEXT,
        UNIQUE(chat_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS group_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        user_id TEXT,
        text TEXT,
        kind TEXT DEFAULT 'text',
        meta TEXT,
        reply_to INTEGER,
        edited_at TEXT,
        deleted INTEGER DEFAULT 0,
        deleted_at TEXT,
        pinned INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS reactions (
        chat_kind TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        user_id TEXT,
        value TEXT,
        created_at TEXT,
        UNIQUE(chat_kind, chat_id, message_id, user_id, value)
    );
    CREATE TABLE IF NOT EXISTS poll_votes (
        chat_kind TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        user_id TEXT,
        choice INTEGER,
        created_at TEXT,
        UNIQUE(chat_kind, chat_id, message_id, user_id, choice)
    );
    CREATE TABLE IF NOT EXISTS teammates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        mate_user_id TEXT,
        note TEXT,
        created_at TEXT,
        UNIQUE(user_id, mate_user_id)
    );
    CREATE TABLE IF NOT EXISTS party_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        party_id INTEGER,
        chat_id INTEGER,
        game_id TEXT,
        leader_user_id TEXT,
        members TEXT,
        started_at TEXT,
        ended_at TEXT,
        minutes INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_gm_chat ON group_messages(chat_id, id);
    CREATE INDEX IF NOT EXISTS idx_gmembers_user ON group_members(user_id);
    """)
    # отметка присутствия у самого пользователя (анкеты может и не быть)
    for col, ddl in (("online", "ALTER TABLE users ADD COLUMN online INTEGER DEFAULT 0"),
                     ("last_seen", "ALTER TABLE users ADD COLUMN last_seen TEXT")):
        if col not in {r[1] for r in conn.execute("PRAGMA table_info(users)")}:
            conn.execute(ddl)
    # опросы: в многовариантных один игрок может выбрать несколько строк —
    # перестраиваем таблицу, если она осталась от версии с одной строкой на игрока
    pv_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='poll_votes'").fetchone()
    if pv_sql and pv_sql["sql"] and "user_id, choice" not in pv_sql["sql"]:
        conn.execute("ALTER TABLE poll_votes RENAME TO poll_votes_old")
        conn.execute("""CREATE TABLE poll_votes (
            chat_kind TEXT, chat_id INTEGER, message_id INTEGER, user_id TEXT, choice INTEGER,
            created_at TEXT, UNIQUE(chat_kind, chat_id, message_id, user_id, choice))""")
        conn.execute("INSERT OR IGNORE INTO poll_votes (chat_kind, chat_id, message_id, user_id, choice, created_at) "
                     "SELECT chat_kind, chat_id, message_id, user_id, choice, created_at FROM poll_votes_old")
        conn.execute("DROP TABLE poll_votes_old")
        conn.commit()
    # личные сообщения: тип и данные карточек (приглашение, поиск игроков), закрепление
    for col, ddl in (("kind", "ALTER TABLE messages ADD COLUMN kind TEXT DEFAULT 'text'"),
                     ("meta", "ALTER TABLE messages ADD COLUMN meta TEXT"),
                     ("pinned", "ALTER TABLE messages ADD COLUMN pinned INTEGER DEFAULT 0")):
        if col not in {r[1] for r in conn.execute("PRAGMA table_info(messages)")}:
            conn.execute(ddl)
    if "typing_at" not in {r[1] for r in conn.execute("PRAGMA table_info(group_members)")}:
        conn.execute("ALTER TABLE group_members ADD COLUMN typing_at TEXT")
    # диалоги: запросы на переписку от незнакомцев и «без звука»
    for col, ddl in (("requested", "ALTER TABLE chats ADD COLUMN requested INTEGER DEFAULT 0"),
                     ("muted_until", "ALTER TABLE chats ADD COLUMN muted_until TEXT"),
                     ("requester_id", "ALTER TABLE chats ADD COLUMN requester_id TEXT")):
        if col not in {r[1] for r in conn.execute("PRAGMA table_info(chats)")}:
            conn.execute(ddl)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "contact" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN contact TEXT DEFAULT ''")
    if "looking_at" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN looking_at TEXT")
    chats_cols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()}
    if "peer_user_id" not in chats_cols:
        conn.execute("ALTER TABLE chats ADD COLUMN peer_user_id TEXT")
    if "unread_b" not in chats_cols:
        conn.execute("ALTER TABLE chats ADD COLUMN unread_b INTEGER DEFAULT 0")
    listing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "reports_count" not in listing_cols:
        conn.execute("ALTER TABLE listings ADD COLUMN reports_count INTEGER DEFAULT 0")
    if "hidden" not in listing_cols:
        conn.execute("ALTER TABLE listings ADD COLUMN hidden INTEGER DEFAULT 0")
    users_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "discord_id" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN discord_id TEXT")
    if "discord_username" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN discord_username TEXT")
    if "password_hash" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if "steam_id" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN steam_id TEXT")
    if "steam_nick" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN steam_nick TEXT")
    if "steam_avatar" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN steam_avatar TEXT")
    # --- чат: ответы на сообщения, правка, удаление, «печатает», прочтение ---
    msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    if "reply_to" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN reply_to INTEGER")
    if "edited_at" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN edited_at TEXT")
    if "deleted" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0")
    if "deleted_at" not in msg_cols:
        conn.execute("ALTER TABLE messages ADD COLUMN deleted_at TEXT")
    chat_cols = {r[1] for r in conn.execute("PRAGMA table_info(chats)")}
    for col in ("typing_a", "typing_b", "read_a", "read_b"):
        if col not in chat_cols:
            conn.execute(f"ALTER TABLE chats ADD COLUMN {col} TEXT")

    if "steam_linked_at" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN steam_linked_at TEXT")
    if "steam_public" not in users_cols:
        conn.execute("ALTER TABLE users ADD COLUMN steam_public INTEGER DEFAULT 1")
    # один Steam-аккаунт — только к одной анкете
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_steam ON users(steam_id) "
                 "WHERE steam_id IS NOT NULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS player_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id INTEGER,
        user_id TEXT,
        author TEXT,
        rating INTEGER,
        text TEXT,
        created_at TEXT,
        UNIQUE(listing_id, user_id)
    )""")
    conn.commit()


def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------------------------------------------
# HTTP-клиент для OAuth (стандартная библиотека, без requests)
# ----------------------------------------------------------------------------

def http_json(url, data=None, headers=None, form=False, timeout=12):
    import urllib.parse
    import urllib.request
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "SQUADUP/1.0")
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


# --- пароли аккаунтов -------------------------------------------------------
# Храним только производный ключ PBKDF2-HMAC-SHA256 с индивидуальной солью.
# Сам пароль не сохраняется и не может быть восстановлен из базы.
PASSWORD_ITERATIONS = 120000
PASSWORD_MIN = 6

LOGIN_ATTEMPTS = {}          # "ник|ip" -> [попытки, время первой]
LOGIN_LOCK = threading.Lock()
LOGIN_MAX_ATTEMPTS = 12
LOGIN_WINDOW_SEC = 600


def hash_password(password):
    import hashlib
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    import hashlib
    import hmac
    if not stored:
        return False
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001
        return False


def login_rate_check(key):
    """Простая защита от перебора: не больше 12 неудачных попыток за 10 минут."""
    import time as _time
    now = _time.time()
    with LOGIN_LOCK:
        stale = [k for k, v in LOGIN_ATTEMPTS.items() if now - v[1] > LOGIN_WINDOW_SEC]
        for k in stale:
            LOGIN_ATTEMPTS.pop(k, None)
        cnt, first = LOGIN_ATTEMPTS.get(key, [0, now])
        if cnt >= LOGIN_MAX_ATTEMPTS:
            return False, int(LOGIN_WINDOW_SEC - (now - first))
        return True, 0


def login_rate_fail(key):
    import time as _time
    with LOGIN_LOCK:
        cnt, first = LOGIN_ATTEMPTS.get(key, [0, _time.time()])
        LOGIN_ATTEMPTS[key] = [cnt + 1, first]


def login_rate_reset(key):
    with LOGIN_LOCK:
        LOGIN_ATTEMPTS.pop(key, None)


def steam_fetch_profile(steam_id):
    """Ник и аватар из публичного профиля Steam. Если профиль закрыт, Steam ограничил запросы
    или сети нет — возвращаем пустые значения: привязка всё равно работает, SteamID подтверждён."""
    import time as _time
    import urllib.request
    xml = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(STEAM_PROFILE_XML.format(steam_id),
                                         headers={"User-Agent": "SQUADUP/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml = resp.read().decode("utf-8", "replace")
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[steam] профиль недоступен (попытка {attempt}):", exc, flush=True)
            if attempt == 1:
                _time.sleep(1.5)
    if xml is None:
        return dict(nick="", avatar="")

    def tag(name):
        m = re.search(r"<%s><!\[CDATA\[(.*?)\]\]></%s>" % (name, name), xml, re.S)
        if not m:
            m = re.search(r"<%s>(.*?)</%s>" % (name, name), xml, re.S)
        return (m.group(1).strip() if m else "")

    return dict(nick=tag("steamID")[:32], avatar=tag("avatarMedium")[:300])


def steam_verify_openid(params):
    """Проверка ответа Steam на НАШЕМ сервере: отправляем полученные параметры обратно
    в Steam с openid.mode=check_authentication. Доверять параметрам из адресной строки нельзя."""
    import urllib.parse
    import urllib.request
    data = {k: v for k, v in params.items() if k.startswith("openid.")}
    data["openid.mode"] = "check_authentication"
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(STEAM_OPENID_ENDPOINT, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "User-Agent": "SQUADUP/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode("utf-8", "replace")
    return bool(re.search(r"^is_valid:\s*true\s*$", text, re.M))


def prune_oauth_states():
    now = datetime.now(timezone.utc)
    with OAUTH_LOCK:
        stale = [k for k, v in OAUTH_STATES.items() if (now - v["created"]).total_seconds() > 600]
        for k in stale:
            OAUTH_STATES.pop(k, None)


# ----------------------------------------------------------------------------
# Генерация демо-данных
# ----------------------------------------------------------------------------

NICK_A = ["Dark", "Night", "Cyber", "Iron", "Shadow", "Frost", "Rapid", "Silent", "Neo", "Ghost",
          "Zero", "Hyper", "Wild", "Lucky", "Mad", "Cold", "Sky", "Turbo", "Quantum", "Void"]
NICK_B = ["Raven", "Wolf", "Fox", "Falcon", "Viper", "Panda", "Dragon", "Knight", "Ranger", "Titan",
          "Reaper", "Nomad", "Pilot", "Hunter", "Bear", "Lynx", "Storm", "Blade", "Owl", "Bolt"]
NICK_RU = ["КиберКот", "ТёмныйЛис", "Пельмень", "Синичка", "Гром", "Бармалей", "Ёжик", "Чебурашка",
           "КотШрёдингера", "Батя_в_тапках", "Кувалда", "Пирожок", "Компот", "Сгущёнка", "Вафля",
           "Апельсин", "Тапок", "Борщ", "Мурзик", "Гречка", "Шашлык", "Батон", "Ёлка", "Сухарь"]
NICK_SUFFIX = ["", "_ru", "_kz", "GG", "99", "1337", "228", "TV", "xD", "000", "YT", "UA"]

ABOUT_TEMPLATES = [
    "Ищу адекватное пати на вечерние катки. Играю {hours} часов в неделю, микрофон есть, токсиков не переношу.",
    "Нужны тиммейты для {mode}. Коммуникация обязательна, без криков и обвинений — просто играем и побеждаем.",
    "Спокойный игрок, играю {game} давно. Люблю сыгранные составы, а не рандомов. Пишите, если такие же цели.",
    "Хочу собрать постоянный состав по {game}. Готов разбирать реплеи, тренироваться по расписанию и играть турниры.",
    "Только начал(а) в {game}, ищу таких же новичков — вместе веселее и учиться проще. Никакого давления.",
    "Опытный игрок, могу подсказать и научить новичков. Играю вечером после работы, микрофон и дискорд есть.",
    "Ищу людей для длинных кооп-сессий по выходным. {mode} — мой любимый режим. Готов играть по 4–6 часов.",
    "Лёгкий настрой, шутим, но в раунде собираемся. {mode}, вечер, стабильный онлайн — идеальный формат.",
    "Серьёзный подход: разбор ошибок, роли, дефолты. Ищу людей с таким же подходом. {mode}.",
    "Вернулся(ась) в {game} после перерыва, нужна компания, чтобы заново вкатиться и поднять ранг.",
    "Играю ради интереса и общения. {mode} — без ругани, с нормальной атмосферой. Присоединяйтесь!",
    "Нужен второй/третий в группу на {game}. Регулярный онлайн после 19:00, спокойный голос, без оскорблений.",
    "Цель — ранг и хорошие выводы из каток. Обожаю тактику, саппорт-роли и красивые командные файты.",
    "Ищу напарника в {game} для соло/дуо прокачки. Помогу с фармом, если новичок. Микрофон желательно.",
]

REVIEW_TEXTS = [
    "Играли вместе десяток каток — спокойный, не тильтует, хорошо ведёт. Рекомендую!",
    "Отличный тиммейт: вовремя, с микрофоном, реально помогает команде. Ещё сыграем.",
    "Сильный игрок, но иногда слишком серьёзно к ошибкам. В целом — надёжный.",
    "Приятный человек, весело играть, если хочется чилла после работы.",
    "Слушает коллауты, держит роль, не тянет одеяло. Такие нужны в команде.",
    "Хорошо разбирает реплеи и объясняет. Помог мне поднять ранг.",
    "Иногда молчит в голосе, но по механике очень хорош. Сыграю ещё.",
    "Играем уже пару месяцев — стабильный онлайн, нулевой токсик. Идеальный тиммейт.",
    "Собрали с ним пати для ранкеда, взяли 8 побед из 10. Работаем дальше!",
    "Дружелюбный и терпеливый, отлично подходит новичкам для обучения.",
]

REPLIES = [
    "Привет! Да, ищу пати — давай катку сегодня вечером?",
    "О, отлично, я как раз собираю состав. Во сколько ты онлайн?",
    "Привет! Я в деле, только микрофон проверю. Где играем — дискорд?",
    "Хей! Сейчас на работе, но после 19:00 свободен, добавимся?",
    "Согласен, го. Только предупреждаю: я саппорт-мейн, устроит?",
    "Йо! Играл вчера до трёх ночи, но ради хорошего состава я всегда готов",
    "Привет, спасибо за сообщение! Давай сначала пару каток, посмотрим на синергию.",
    "Конечно! По рангу мы примерно равны, должно получиться хорошо.",
    "Я за! Добавь меня в дискорд, ник такой же, как здесь.",
    "Здорово, что написал. Собираю пятёрку к выходным, впишешься?",
]


def gen_nick(rnd, used):
    for _ in range(200):
        if rnd.random() < 0.25:
            nick = rnd.choice(NICK_RU) + rnd.choice(["", "98", "07", "TV", "_RU", ""])
        else:
            nick = rnd.choice(NICK_A) + rnd.choice(NICK_B) + rnd.choice(NICK_SUFFIX)
        if nick not in used:
            used.add(nick)
            return nick
    fallback = "Player" + str(rnd.randint(1000, 999999))
    used.add(fallback)
    return fallback


def gen_seed_listings(count=88):
    rnd = random.Random(20260929)
    used = set()
    # немного «тяжёлых» игроков в популярных играх — чтобы фильтры выглядели живо
    popular = ["cs2", "cs2", "cs2", "valorant", "valorant", "dota2", "dota2", "lol", "pubg", "fortnite",
               "hd2", "mhw", "arc_raiders", "apex", "ow2", "r6", "minecraft", "bg3", "rust", "tarkov",
               "wow", "gta", "marvel_rivals", "deadlock", "bf6", "rl", "sot", "destiny2", "phasmo", "drg"]
    listings = []
    for i in range(count):
        n_games = rnd.choices([1, 2, 3], weights=[0.42, 0.4, 0.18])[0]
        gids = []
        gids.append(rnd.choice(popular) if rnd.random() < 0.6 else rnd.choice(GAMES)["id"])
        while len(gids) < n_games:
            gid = rnd.choice(GAMES)["id"]
            if gid not in gids:
                gids.append(gid)

        games_payload = []
        top_skill = 0
        for gid in gids:
            g = GAME_BY_ID[gid]
            rank_idx = rnd.randint(0, len(g["ranks"]) - 1)
            role = rnd.choice(g["roles"])
            skill = min(5, max(1, round((rank_idx + 1) / len(g["ranks"]) * 4) + 1))
            top_skill = max(top_skill, skill)
            hours = rnd.randint(30, 900) if gid in ("itt", "lethal", "phasmo") else rnd.randint(80, 4200)
            games_payload.append(dict(game_id=gid, rank=g["ranks"][rank_idx], role=role, hours=hours))

        region = rnd.choices([r["id"] for r in REGIONS], weights=[0.4, 0.1, 0.11, 0.07, 0.09, 0.08, 0.06, 0.09])[0]
        langs = ["Русский"] if rnd.random() < 0.55 else rnd.sample(LANGUAGES, k=rnd.randint(2, 3))
        if "Русский" not in langs and rnd.random() < 0.4:
            langs.append("Русский")
        platforms = rnd.sample(["pc", "ps", "xbox"], k=rnd.choices([1, 2, 3], weights=[0.62, 0.3, 0.08])[0])
        vibe = rnd.choices(list(VIBES.keys()), weights=[0.3, 0.4, 0.2, 0.1])[0]
        online = 1 if rnd.random() < 0.58 else 0
        about = rnd.choice(ABOUT_TEMPLATES).format(
            game=GAME_BY_ID[gids[0]]["short"],
            mode=MODE_LABELS[GAME_BY_ID[gids[0]]["modes"][0]].lower() + " режим",
            hours=rnd.choice(["8–12", "12–20", "20+", "5–10"]),
        )
        reviews = []
        for _ in range(rnd.randint(2, 3)):
            reviews.append(dict(author=gen_nick(rnd, used), rating=rnd.choice([4, 4, 5, 5, 3]),
                                text=rnd.choice(REVIEW_TEXTS), date=now_iso(-rnd.randint(100, 40000))))
        listings.append(dict(
            id=None,
            user_id=None,
            nick=gen_nick(rnd, used),
            age=rnd.randint(16, 34),
            region=region,
            platforms=platforms,
            languages=langs,
            skill=top_skill,
            mic=1 if rnd.random() < 0.82 else 0,
            vibe=vibe,
            schedule=sorted(rnd.sample(SCHEDULE_SLOTS, k=rnd.randint(2, 4)),
                            key=lambda s: SCHEDULE_SLOTS.index(s)),
            about=about,
            games=games_payload,
            rating=round(rnd.uniform(3.9, 5.0) if rnd.random() < 0.85 else rnd.uniform(3.2, 3.9), 2),
            reviews_count=rnd.randint(4, 380),
            hours=sum(g["hours"] for g in games_payload),
            online=online,
            verified=1 if rnd.random() < 0.45 else 0,
            last_seen=now_iso(-rnd.randint(0, 5000) if not online else 0),
            reviews=reviews,
            is_seed=1,
            created_at=now_iso(-rnd.randint(100, 200000)),
        ))
    return listings


SQUAD_TEMPLATES = [
    ("Небесные Лисы", "NLFS", ["Уютный, но результативный состав", "Играем вечерами, разбираем ошибки, шутим в голосе"]),
    ("Purple Squad", "PRPL", ["Собираем ростер под регулярные турниры", "Тренировки 3 раза в неделю, разбор реплеев обязателен"]),
    ("Black Lotus", "BLS", ["Состав на длинную дистанцию", "Спокойный голос, чёткие колауты, никакого тильта"]),
    ("Северный Ветер", "NWND", ["Клан для семейных и работающих", "Играем после 20:00, в выходные — большие сессии"]),
    ("Pixel Wolves", "PXWL", ["Кооп отряд для PvE-экспедиций", "Любим сложные модификаторы и хардкор-задания"]),
    ("Iron Bear Company", "IRON", ["Серьёзный коллектив по шутерам", "Требуем стабильный онлайн и микрофон"]),
    ("Каспийская Гвардия", "CSPG", ["Состав по Dota/CS из Казахстана", "Общение на русском, средний пинг к EU-серверам"]),
    ("Moonlit Crew", "MNLT", ["Чилл-сквад для долгих сессий", "Играем по кайфу, но без глупых смертей"]),
    ("Ghost Division", "GHST", ["Extraction-отряд", "Приоритет — вынести лут, а не фраги"]),
    ("Академия Новичков", "ACAD", ["Обучаем новичков", "Разбираем механику, помогаем поднять ранг"]),
    ("Turbo Pigeons", "TRBP", ["Быстрые катки по вечерам", "Играем в 2–3 игры, всегда онлайн в дискорде"]),
    ("Void Runners", "VDRN", ["Хардкор-PvE состав", "Любим самые сложные рейды и испытания"]),
    ("Team Bavaria", "BAVR", ["Состав из центральной Европы", "Общаемся на русском и немецком, играем по CET"]),
    ("Golden Rush", "GLDR", ["Состав под рейтинговые сезоны", "Цель — топ-1000 в своём регионе"]),
]


def gen_seed_squads(count=14):
    rnd = random.Random(777)
    squads = []
    for i in range(count):
        name, tag, (about1, about2) = SQUAD_TEMPLATES[i % len(SQUAD_TEMPLATES)]
        g = GAME_BY_ID[rnd.choice([g["id"] for g in GAMES if "comp" in g["modes"] or "coop" in g["modes"]])]
        mode = g["modes"][0]
        size = rnd.choice([3, 3, 4, 4, 5, 5, 5, 6])
        filled = rnd.randint(1, max(1, size - 1))
        need_roles = rnd.sample(g["roles"], k=min(len(g["roles"]), size - filled))
        region = rnd.choices([r["id"] for r in REGIONS], weights=[0.42, 0.1, 0.12, 0.08, 0.08, 0.08, 0.05, 0.07])[0]
        squads.append(dict(
            name=name, tag=tag, game_id=g["id"], mode=mode, region=region, language=rnd.choice(["Русский", "Русский", "English", "Русский + English"]),
            size=size, filled=filled, need=need_roles,
            min_rank=g["ranks"][max(0, rnd.randint(0, len(g["ranks"]) - 3))],
            mic=1 if rnd.random() < 0.8 else 0,
            schedule=rnd.choice(["Вечер 18–24, выходные", "Ежедневно 19:00–23:00", "Будни 20–24, сб-вс полностью",
                                 "Пн/Ср/Пт 20:00", "Вечер по будням"]),
            about=about1 + ". " + about2 + ".",
            captain=gen_nick(rnd, set()),
            owner_id=None,
            created_at=now_iso(-rnd.randint(1000, 300000)),
        ))
    return squads


def purge_demo_data(conn):
    """Убирает демонстрационные записи, если демо-режим выключен.

    Демо-анкеты и скводы легко отличить от настоящих: у них нет владельца
    (user_id / owner_id пусты), а у анкет стоит пометка is_seed. Вместе с ними
    удаляются диалоги «для приветствия» — иначе в чатах остались бы сообщения
    от игроков, которых на самом деле нет. Вызывается внутри init_db (замок уже взят).
    """
    seed_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM listings WHERE is_seed = 1 AND user_id IS NULL")]
    squads = conn.execute("DELETE FROM squads WHERE owner_id IS NULL").rowcount
    chats = 0
    if seed_ids:
        marks = ",".join("?" * len(seed_ids))
        chats = conn.execute(f"DELETE FROM chats WHERE listing_id IN ({marks})", seed_ids).rowcount
        conn.execute(f"DELETE FROM listings WHERE id IN ({marks})", seed_ids)
    # аккаунты, созданные старым демо-входом «по одному нику»: ни пароля, ни Discord, ни Steam.
    # Войти в них больше нельзя (пароль обязателен), а ник остаётся занятым — поэтому убираем.
    ghosts = [r["id"] for r in conn.execute(
        "SELECT id FROM users WHERE password_hash IS NULL AND discord_id IS NULL AND steam_id IS NULL")]
    if ghosts:
        marks = ",".join("?" * len(ghosts))
        conn.execute(f"DELETE FROM listings WHERE user_id IN ({marks})", ghosts)
        conn.execute(f"DELETE FROM chats WHERE user_id IN ({marks}) OR peer_user_id IN ({marks})", ghosts + ghosts)
        for table in ("blocks", "applications", "push_subscriptions"):
            try:
                conn.execute(f"DELETE FROM {table} WHERE user_id IN ({marks})", ghosts)
            except Exception:
                pass
        try:
            conn.execute(f"DELETE FROM reports WHERE reporter_id IN ({marks})", ghosts)
        except Exception:
            pass
        conn.execute(f"DELETE FROM users WHERE id IN ({marks})", ghosts)
    messages = conn.execute("DELETE FROM messages WHERE chat_id NOT IN (SELECT id FROM chats)").rowcount
    return dict(listings=len(seed_ids), squads=squads, chats=chats, users=len(ghosts), messages=messages)


def init_db():
    fresh = not os.path.exists(DB_PATH)
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    conn = db_connect()
    with DB_LOCK:
        conn.executescript(SCHEMA)
        migrate(conn)
        cur = conn.execute("SELECT COUNT(*) AS c FROM listings WHERE is_seed = 1 AND user_id IS NULL")
        if DEMO_DATA and cur.fetchone()["c"] == 0:
            for l in gen_seed_listings():
                conn.execute(
                    """INSERT INTO listings (user_id,nick,age,region,platforms,languages,skill,mic,vibe,schedule,
                       about,games,rating,reviews_count,hours,online,verified,last_seen,reviews,is_seed,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (l["user_id"], l["nick"], l["age"], l["region"], json.dumps(l["platforms"], ensure_ascii=False),
                     json.dumps(l["languages"], ensure_ascii=False), l["skill"], l["mic"], l["vibe"],
                     json.dumps(l["schedule"], ensure_ascii=False), l["about"],
                     json.dumps(l["games"], ensure_ascii=False), l["rating"], l["reviews_count"], l["hours"],
                     l["online"], l["verified"], l["last_seen"], json.dumps(l["reviews"], ensure_ascii=False),
                     l["is_seed"], l["created_at"]),
                )
        cur = conn.execute("SELECT COUNT(*) AS c FROM squads WHERE owner_id IS NULL")
        if DEMO_DATA and cur.fetchone()["c"] == 0:
            for s in gen_seed_squads():
                conn.execute(
                    """INSERT INTO squads (name,tag,game_id,mode,region,language,size,filled,need,min_rank,mic,schedule,
                       about,captain,owner_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (s["name"], s["tag"], s["game_id"], s["mode"], s["region"], s["language"], s["size"], s["filled"],
                     json.dumps(s["need"], ensure_ascii=False), s["min_rank"], s["mic"], s["schedule"], s["about"],
                     s["captain"], s["owner_id"], s["created_at"]),
                )
        if not DEMO_DATA:
            gone = purge_demo_data(conn)
            if any(gone.values()):
                print("[db] демо-записи убраны:", gone, flush=True)
        conn.commit()
    conn.close()
    if fresh:
        print("[db] база готова:", DB_PATH, "| демо-данные:", "включены" if DEMO_DATA else "выключены")


# ----------------------------------------------------------------------------
# Сериализация
# ----------------------------------------------------------------------------

def row_to_listing(row, current_user_id=None, full=False, conn=None):
    games = json.loads(row["games"] or "[]")
    keys = row.keys()
    # Steam показываем только если владелец анкеты разрешил это в настройках
    steam_nick, steam_url, avatar = "", "", ""
    if conn is not None and "user_id" in keys and row["user_id"]:
        su = conn.execute("SELECT steam_id, steam_nick, steam_avatar, steam_public FROM users WHERE id = ?",
                          (row["user_id"],)).fetchone()
        if su and su["steam_id"] and (su["steam_public"] is None or su["steam_public"]):
            steam_nick = su["steam_nick"] or ""
            steam_url = "https://steamcommunity.com/profiles/" + su["steam_id"]
            avatar = su["steam_avatar"] or ""
    looking_at = row["looking_at"] if "looking_at" in keys else None
    is_looking = bool(looking_at and looking_at >= iso_cutoff(LOOKING_WINDOW_MIN))
    out = dict(
        id=row["id"],
        nick=row["nick"],
        age=row["age"],
        region=row["region"],
        region_label=REGION_BY_ID.get(row["region"], {}).get("label", row["region"]),
        platforms=json.loads(row["platforms"] or "[]"),
        languages=json.loads(row["languages"] or "[]"),
        steam_nick=steam_nick,
        steam_url=steam_url,
        avatar=avatar,
        skill=row["skill"],
        skill_label=SKILL_LABELS.get(row["skill"], ""),
        mic=row["mic"],
        vibe=row["vibe"],
        vibe_label=VIBES.get(row["vibe"], row["vibe"]),
        schedule=json.loads(row["schedule"] or "[]"),
        about=row["about"],
        games=[dict(g, name=GAME_BY_ID[g["game_id"]]["name"], short=GAME_BY_ID[g["game_id"]]["short"],
                    genre=GAME_BY_ID[g["game_id"]]["genre"],
                    modes=GAME_BY_ID[g["game_id"]]["modes"]) for g in games if g["game_id"] in GAME_BY_ID],
        rating=row["rating"],
        reviews_count=row["reviews_count"],
        hours=row["hours"],
        online=row["online"],
        verified=row["verified"],
        last_seen=row["last_seen"],
        is_me=bool(current_user_id and row["user_id"] == current_user_id),
        created_at=row["created_at"],
        contact=(row["contact"] or "") if "contact" in keys else "",
        looking_at=looking_at,
        is_looking=is_looking,
    )
    if full:
        fresh_reviews = []
        my_review = None
        if conn is not None:
            for r in conn.execute(
                    "SELECT * FROM player_reviews WHERE listing_id = ? ORDER BY id DESC", (row["id"],)):
                fresh_reviews.append(dict(author=r["author"] or "Игрок", rating=r["rating"],
                                          text=r["text"], date=r["created_at"]))
                if current_user_id and r["user_id"] == current_user_id:
                    my_review = dict(rating=r["rating"], text=r["text"])
        out["reviews"] = fresh_reviews + json.loads(row["reviews"] or "[]")
        out["my_review"] = my_review
    return out


def row_to_squad(row, current_user_id=None, applied_ids=None):
    g = GAME_BY_ID.get(row["game_id"], {})
    applied_ids = applied_ids or set()
    return dict(
        id=row["id"],
        name=row["name"],
        tag=row["tag"],
        game_id=row["game_id"],
        game_name=g.get("name", row["game_id"]),
        game_short=g.get("short", row["game_id"]),
        mode=row["mode"],
        mode_label=MODE_LABELS.get(row["mode"], row["mode"]),
        region=row["region"],
        region_label=REGION_BY_ID.get(row["region"], {}).get("label", row["region"]),
        language=row["language"],
        size=row["size"],
        filled=row["filled"],
        need=json.loads(row["need"] or "[]"),
        min_rank=row["min_rank"],
        mic=row["mic"],
        schedule=row["schedule"],
        about=row["about"],
        captain=row["captain"],
        is_mine=bool(current_user_id and row["owner_id"] == current_user_id),
        applied=row["id"] in applied_ids,
        created_at=row["created_at"],
    )


# ----------------------------------------------------------------------------
# HTTP-обработчик
# ----------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SQUADUP/1.0"
    protocol_version = "HTTP/1.1"

    # --- утилиты ---
    def log_message(self, fmt, *args):
        if os.environ.get("SQUADUP_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, code, body, content_type="application/json; charset=utf-8",
              cache="no-store", headers=None, compress=True):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        extra = []
        if compress and len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            import gzip as _gzip
            body = _gzip.compress(body, 6)
            extra.append(("Content-Encoding", "gzip"))
            extra.append(("Vary", "Accept-Encoding"))
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Cache-Control", cache)
        for k, v in extra:
            self.send_header(k, v)
        for k, v in (headers or []):
            self.send_header(k, v)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _user(self, conn):
        token = self.headers.get("X-Token")
        if not token:
            return None
        row = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()
        if row:
            # каждый запрос — знак, что игрок в сети (в базу пишем не чаще раза в 30 секунд)
            fresh = conn.execute("SELECT last_seen FROM users WHERE id = ? AND last_seen >= ?",
                                 (row["id"], iso_cutoff(0.5))).fetchone()
            if not fresh:
                touch_presence(conn, row["id"])
                conn.commit()
        return row

    def _redirect(self, location):
        return self._send(302, b"", "text/plain; charset=utf-8", cache="no-store",
                          headers=[("Location", location)])

    def base_url(self):
        host = self.headers.get("Host") or f"localhost:{PORT}"
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        return f"{proto}://{host}"

    def do_OPTIONS(self):
        self._send(204, b"")

    def do_HEAD(self):
        self._head_only = True
        try:
            self.route("GET")
        finally:
            self._head_only = False

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    # --- роутер ---
    def route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        conn = db_connect()
        try:
            # health-check для облачных платформ (Railway, Render, Docker)
            if path == "/.well-known/assetlinks.json" and method == "GET":
                # Digital Asset Links: подтверждает, что Android-приложение
                # (TWA) имеет право открывать сайт на весь экран без адресной строки.
                pkg = os.environ.get("TWA_PACKAGE_NAME", "app.squadup.twa")
                fingerprints = [f.strip() for f in
                                os.environ.get("TWA_SHA256_FINGERPRINTS", "").split(",") if f.strip()]
                return self._send(200, [dict(
                    relation=["delegate_permission/common.handle_all_urls"],
                    target=dict(namespace="android_app", package_name=pkg,
                                sha256_cert_fingerprints=fingerprints or ["ЗАПОЛНИ_ПОСЛЕ_ПОДПИСИ_APK"]),
                )])
            if path in ("/healthz", "/api/healthz") and method == "GET":
                return self._send(200, dict(ok=True, db=os.path.basename(DB_PATH), games=len(GAMES)))
            if path.startswith("/uploads/"):
                return self.serve_upload(path)

            if path.startswith("/api/"):
                return self.handle_api(method, path, query, conn)
            if method == "GET":
                return self.serve_static(path)
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            import traceback
            print(f"[500] {method} {path}: {exc}", flush=True)
            traceback.print_exc()
            return self._send(500, {"error": str(exc)})
        finally:
            conn.close()

    # --- статика ---
    MIME = {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".ico": "image/x-icon",
        ".json": "application/json; charset=utf-8",
        ".webmanifest": "application/manifest+json; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".woff2": "font/woff2",
    }

    def serve_upload(self, path):
        name = os.path.basename(path)
        full = os.path.join(UPLOADS_DIR, name)
        if not os.path.isfile(full):
            return self._send(404, {"error": "Файл не найден"})
        ctype = self.MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        return self._send(200, data, ctype, cache="public, max-age=86400")

    def serve_static(self, path):
        rel = "index.html" if path == "/" else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            return self._send(404, "<h1>404</h1>", "text/html; charset=utf-8")
        ext = os.path.splitext(full)[1].lower()
        ctype = self.MIME.get(ext, "application/octet-stream")
        # index.html и sw.js должны перечитываться, иконки можно кэшировать
        if ext in (".html", ".js") or rel in ("sw.js", "index.html"):
            cache = "no-cache"
        else:
            cache = "public, max-age=86400"
        with open(full, "rb") as fh:
            data = fh.read()
        return self._send(200, data, ctype, cache=cache)

    # --- API ---
    def handle_api(self, method, path, query, conn):
        user = self._user(conn)
        uid = user["id"] if user else None

        # --- служебное ---
        if path == "/api/config" and method == "GET":
            return self._send(200, dict(discord_enabled=DISCORD_ENABLED,
                                        steam_enabled=True,
                                        push_enabled=PUSH_ENABLED,
                                        app_name="SQUADUP", version="1.11.1"))

        if path == "/api/games" and method == "GET":
            return self._send(200, dict(
                games=GAMES, platforms=PLATFORM_LABELS, modes=MODE_LABELS,
                regions=REGIONS, skills=SKILL_LABELS, vibes=VIBES, schedule_slots=SCHEDULE_SLOTS,
                languages=LANGUAGES,
            ))

        if path == "/api/login" and method == "POST":
            body = self._json_body()
            nick = (body.get("nickname") or "").strip()[:32]
            password = str(body.get("password") or "")
            if len(nick) < 2:
                return self._send(400, {"error": "Ник должен быть не короче 2 символов"})
            # за прокси хостинга реальный адрес приходит в X-Forwarded-For
            fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            client_ip = fwd or (self.client_address[0] if self.client_address else "?")
            rk = (nick.lower() + "|" + client_ip)
            allowed, wait = login_rate_check(rk)
            if not allowed:
                return self._send(429, {"error": f"Слишком много попыток входа. Подожди {max(1, wait // 60)} мин."})
            row = conn.execute("SELECT * FROM users WHERE nickname = ? COLLATE NOCASE", (nick,)).fetchone()

            # Аккаунт уже есть
            if row:
                stored = row["password_hash"] if "password_hash" in row.keys() else None
                if stored:
                    if not password:
                        login_rate_fail(rk)
                        return self._send(400, {"error": "Введите пароль от аккаунта", "need_password": True})
                    if not verify_password(password, stored):
                        login_rate_fail(rk)
                        return self._send(401, {"error": "Неверный пароль", "need_password": True})
                    login_rate_reset(rk)
                    return self._send(200, dict(token=row["token"], user_id=row["id"],
                                                nickname=row["nickname"], created=False))
                # Аккаунт без пароля: либо создан до появления паролей, либо вход был через Discord/Steam.
                oauth_linked = bool((row["discord_id"] if "discord_id" in row.keys() else None) or
                                    (row["steam_id"] if "steam_id" in row.keys() else None))
                if oauth_linked:
                    return self._send(403, {"error": "Этот ник привязан к Discord или Steam — войди через них "
                                                     "или выбери другой ник"})
                # Придумываем пароль: одноразовый токен на 10 минут
                if len(password) < PASSWORD_MIN:
                    return self._send(200, dict(needs_password=True, nickname=row["nickname"],
                                                error=f"Придумай пароль не короче {PASSWORD_MIN} символов"))
                setup = uuid.uuid4().hex
                with OAUTH_LOCK:
                    OAUTH_STATES[setup] = dict(created=datetime.now(timezone.utc), link_uid=row["id"],
                                               kind="password_setup")
                return self._send(200, dict(needs_password=True, setup_token=setup,
                                            nickname=row["nickname"]))

            # Новый аккаунт
            if len(password) < PASSWORD_MIN:
                return self._send(400, {"error": f"Придумай пароль не короче {PASSWORD_MIN} символов"})
            uid, token = str(uuid.uuid4()), uuid.uuid4().hex
            conn.execute("""INSERT INTO users (id, token, nickname, created_at, password_hash)
                            VALUES (?,?,?,?,?)""",
                         (uid, token, nick, now_iso(), hash_password(password)))
            conn.commit()
            self.seed_welcome_chats(conn, uid)
            login_rate_reset(rk)
            return self._send(200, dict(token=token, user_id=uid, nickname=nick, created=True))

        if path == "/api/password/setup" and method == "POST":
            body = self._json_body()
            setup = (body.get("setup_token") or "").strip()
            password = str(body.get("password") or "")
            with OAUTH_LOCK:
                st = OAUTH_STATES.pop(setup, None)
            if not st or st.get("kind") != "password_setup":
                return self._send(400, {"error": "Ссылка устарела — попробуй войти заново"})
            if len(password) < PASSWORD_MIN:
                return self._send(400, {"error": f"Пароль должен быть не короче {PASSWORD_MIN} символов"})
            token = uuid.uuid4().hex          # новый токен: старые сессии перестают работать
            conn.execute("UPDATE users SET password_hash = ?, token = ? WHERE id = ?",
                         (hash_password(password), token, st["link_uid"]))
            conn.commit()
            row = conn.execute("SELECT nickname FROM users WHERE id = ?", (st["link_uid"],)).fetchone()
            return self._send(200, dict(token=token, user_id=st["link_uid"], nickname=row["nickname"]))

        if path == "/api/me/password" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            old_password = str(body.get("old_password") or "")
            new_password = str(body.get("new_password") or "")
            stored = user["password_hash"] if "password_hash" in user.keys() else None
            if stored and not verify_password(old_password, stored):
                return self._send(403, {"error": "Текущий пароль указан неверно"})
            if len(new_password) < PASSWORD_MIN:
                return self._send(400, {"error": f"Новый пароль должен быть не короче {PASSWORD_MIN} символов"})
            token = uuid.uuid4().hex           # меняем пароль — меняем и сессию
            conn.execute("UPDATE users SET password_hash = ?, token = ? WHERE id = ?",
                         (hash_password(new_password), token, uid))
            conn.commit()
            return self._send(200, dict(ok=True, token=token))

        if path == "/api/me/has-password" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            stored = user["password_hash"] if "password_hash" in user.keys() else None
            return self._send(200, dict(has_password=bool(stored)))

        if path == "/api/report" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            ttype = body.get("target_type")
            try:
                tid = int(body.get("target_id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "Некорректная цель жалобы"})
            reason = body.get("reason") if body.get("reason") in REPORT_REASONS else "other"
            comment = (body.get("comment") or "").strip()[:500]
            # одна жалоба на цель от одного пользователя — иначе счётчик накрутит один человек
            if conn.execute("SELECT 1 FROM reports WHERE reporter_id = ? AND target_type = ? AND target_id = ?",
                            (uid, ttype, tid)).fetchone():
                return self._send(200, dict(ok=True, already=True, hidden=False, reports_count=None,
                                            message="Ты уже жаловался на это — жалоба на проверке у модерации."))
            target_nick = ""
            if ttype == "player":
                row = conn.execute("SELECT * FROM listings WHERE id = ?", (tid,)).fetchone()
                if not row:
                    return self._send(404, {"error": "Анкета не найдена"})
                if row["user_id"] == uid:
                    return self._send(400, {"error": "Нельзя жаловаться на себя"})
                target_nick = row["nick"]
                conn.execute("UPDATE listings SET reports_count = reports_count + 1 WHERE id = ?", (tid,))
                fresh = conn.execute("SELECT reports_count FROM listings WHERE id = ?", (tid,)).fetchone()["reports_count"]
                hidden = False
                if fresh >= MODERATION_HIDE_THRESHOLD:
                    conn.execute("UPDATE listings SET hidden = 1 WHERE id = ?", (tid,))
                    hidden = True
            elif ttype == "squad":
                row = conn.execute("SELECT * FROM squads WHERE id = ?", (tid,)).fetchone()
                if not row:
                    return self._send(404, {"error": "Сквад не найден"})
                target_nick = row["name"]
                hidden = False
            elif ttype == "message":
                row = conn.execute("SELECT * FROM messages WHERE id = ?", (tid,)).fetchone()
                if not row:
                    return self._send(404, {"error": "Сообщение не найдено"})
                target_nick = (row["text"] or "")[:60]
                hidden = False
            else:
                return self._send(400, {"error": "Неизвестный тип цели"})
            conn.execute("""INSERT INTO reports (reporter_id, reporter_nick, target_type, target_id,
                            target_nick, reason, comment, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                         (uid, user["nickname"], ttype, tid, target_nick, reason, comment, now_iso()))
            conn.commit()
            return self._send(200, dict(ok=True, hidden=hidden,
                                        reports_count=(fresh if ttype == "player" else 0),
                                        message="Жалоба отправлена. Спасибо — модерация проверит." +
                                                (" Анкета временно скрыта из поиска." if hidden else "")))

        if path == "/api/block" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            target_uid = None
            nick = ""
            if body.get("listing_id"):
                row = conn.execute("SELECT * FROM listings WHERE id = ?", (int(body["listing_id"]),)).fetchone()
                if not row:
                    return self._send(404, {"error": "Анкета не найдена"})
                target_uid, nick = row["user_id"], row["nick"]
            elif body.get("chat_id"):
                c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                 (int(body["chat_id"]), uid, uid)).fetchone()
                if not c:
                    return self._send(404, {"error": "Чат не найден"})
                target_uid, nick, _, _ = chat_partner(conn, c, uid)
            else:
                return self._send(400, {"error": "Не указан игрок"})
            if not target_uid:
                return self._send(400, {"error": "Это демо-анкета — блокировать некого"})
            if target_uid == uid:
                return self._send(400, {"error": "Нельзя заблокировать себя"})
            conn.execute("""INSERT INTO blocks (user_id, blocked_user_id, blocked_nick, created_at)
                            VALUES (?,?,?,?) ON CONFLICT(user_id, blocked_user_id) DO NOTHING""",
                         (uid, target_uid, nick or user_display(conn, target_uid), now_iso()))
            conn.commit()
            return self._send(200, dict(ok=True, blocked_nick=nick or user_display(conn, target_uid)))

        if path == "/api/unblock" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            bid = (body.get("blocked_user_id") or "").strip()
            if not bid:
                return self._send(400, {"error": "Не указан игрок"})
            conn.execute("DELETE FROM blocks WHERE user_id = ? AND blocked_user_id = ?", (uid, bid))
            conn.commit()
            return self._send(200, dict(ok=True))

        if path == "/api/blocks" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            rows = conn.execute("SELECT * FROM blocks WHERE user_id = ? ORDER BY id DESC", (uid,)).fetchall()
            items = []
            for r in rows:
                nick = r["blocked_nick"] or user_display(conn, r["blocked_user_id"])
                items.append(dict(blocked_user_id=r["blocked_user_id"], nick=nick, created_at=r["created_at"]))
            return self._send(200, dict(items=items, reasons=REPORT_REASONS))

        if path in ("/api/admin/backup", "/api/admin/restore"):
            admin_key = os.environ.get("ADMIN_KEY", "").strip()
            provided = (query.get("key") or [""])[0] or (self.headers.get("X-Admin-Key") or "")
            if not admin_key:
                return self._send(403, {"error": "Резервные копии не настроены: задай ADMIN_KEY"})
            if provided != admin_key:
                return self._send(403, {"error": "Неверный ключ администратора"})
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            if path == "/api/admin/backup" and method == "GET":
                data = {t: [dict(r) for r in conn.execute("SELECT * FROM %s" % t)] for t in tables}
                return self._send(200, dict(version=1, created_at=now_iso(), app="SQUADUP", tables=data))
            if path == "/api/admin/restore" and method == "POST":
                body = self._json_body()
                incoming = body.get("tables") or {}
                if not incoming:
                    return self._send(400, {"error": "В файле нет данных для восстановления"})
                restored = {}
                for t in tables:
                    rows = incoming.get(t)
                    if rows is None:
                        continue
                    cols = [r["name"] for r in conn.execute("PRAGMA table_info(%s)" % t)]
                    conn.execute("DELETE FROM %s" % t)
                    for row in rows:
                        use = [c for c in cols if c in row]
                        if not use:
                            continue
                        conn.execute("INSERT INTO %s (%s) VALUES (%s)" % (
                            t, ", ".join(use), ", ".join("?" * len(use))), [row[c] for c in use])
                    restored[t] = len(rows)
                conn.commit()
                return self._send(200, dict(ok=True, restored=restored))

        if path == "/api/admin/reports" and method == "GET":
            # Простая модерация: доступ по ключу ADMIN_KEY (задаётся переменной окружения).
            admin_key = os.environ.get("ADMIN_KEY", "").strip()
            provided = (query.get("key") or [""])[0] or (self.headers.get("X-Admin-Key") or "")
            if not admin_key:
                return self._send(403, {"error": "Модерация не настроена: задай переменную ADMIN_KEY"})
            if provided != admin_key:
                return self._send(403, {"error": "Неверный ключ модератора"})
            # по умолчанию показываем только необработанные жалобы; status=all — все
            status = (query.get("status") or ["new"])[0].strip() or "new"
            sql = "SELECT * FROM reports"
            args = ()
            if status != "all":
                sql += " WHERE status = ?"
                args = ("new" if status in ("open", "active") else status,)
            sql += " ORDER BY id DESC LIMIT 200"
            rows = conn.execute(sql, args).fetchall()
            hidden = conn.execute("SELECT id, nick, reports_count FROM listings WHERE hidden = 1").fetchall()
            return self._send(200, dict(
                reports=[dict(id=r["id"], who=r["reporter_nick"], target_type=r["target_type"],
                              target_id=r["target_id"], target=r["target_nick"],
                              reason=REPORT_REASONS.get(r["reason"], r["reason"]),
                              comment=r["comment"], status=r["status"], created_at=r["created_at"])
                         for r in rows],
                hidden_listings=[dict(id=h["id"], nick=h["nick"], reports=h["reports_count"]) for h in hidden],
                reasons=REPORT_REASONS))

        if path == "/api/admin/report-resolve" and method == "POST":
            admin_key = os.environ.get("ADMIN_KEY", "").strip()
            body = self._json_body()          # тело читаем один раз: повторный read вернёт пустоту
            provided = self.headers.get("X-Admin-Key") or (body.get("key") or "")
            if not admin_key or provided != admin_key:
                return self._send(403, {"error": "Доступ только для модератора"})
            try:
                rid = int(body.get("report_id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "Некорректная жалоба"})
            decision = body.get("decision")  # 'dismiss' | 'hide' | 'restore'
            if decision not in ("dismiss", "hide", "restore"):
                return self._send(400, {"error": "Решение: dismiss, hide или restore"})
            rep = conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
            if not rep:
                return self._send(404, {"error": "Жалоба не найдена"})
            conn.execute("UPDATE reports SET status = ? WHERE id = ?", (decision, rid))
            if rep["target_type"] == "player":
                if decision == "hide":
                    conn.execute("UPDATE listings SET hidden = 1 WHERE id = ?", (rep["target_id"],))
                elif decision == "restore":
                    conn.execute("UPDATE listings SET hidden = 0, reports_count = 0 WHERE id = ?", (rep["target_id"],))
            conn.commit()
            return self._send(200, dict(ok=True))

        # --- Данные пользователя: экспорт и удаление (требование магазинов) ---
        if path == "/api/me/export" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            listings_rows = conn.execute("SELECT * FROM listings WHERE user_id = ? ORDER BY id", (uid,)).fetchall()
            chats = conn.execute("SELECT * FROM chats WHERE user_id = ?", (uid,)).fetchall()
            chat_export = []
            for c in chats:
                msgs = conn.execute("SELECT sender, text, created_at FROM messages WHERE chat_id = ? ORDER BY id",
                                    (c["id"],)).fetchall()
                chat_export.append(dict(peer=c["peer_nick"], listing_id=c["listing_id"],
                                        messages=[dict(m) for m in msgs]))
            apps_rows = conn.execute("""SELECT a.id, s.name AS squad, a.message, a.status, a.created_at
                                        FROM applications a LEFT JOIN squads s ON s.id = a.squad_id
                                        WHERE a.user_id = ?""", (uid,)).fetchall()
            subs = conn.execute("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?",
                                (uid,)).fetchone()["c"]
            giveaway = dict(
                exported_at=now_iso(),
                account=dict(nickname=user["nickname"],
                             discord_username=user["discord_username"] if "discord_username" in user.keys() else None,
                             registered_at=user["created_at"]),
                listings=[row_to_listing(r, uid, full=True, conn=conn) for r in listings_rows],
                chats=chat_export,
                squad_applications=[dict(a) for a in apps_rows],
                push_devices=subs,
                note="Полная копия твоих данных в SQUADUP. Файл можно открыть в любом текстовом редакторе.",
            )
            body = json.dumps(giveaway, ensure_ascii=False, indent=2).encode("utf-8")
            # имя файла только из ASCII-символов: кириллица в HTTP-заголовке недопустима
            safe_nick = re.sub(r"[^A-Za-z0-9_.-]+", "_", user["nickname"]).strip("_")[:40] or ("user-" + uid[:8])
            return self._send(200, body, "application/json; charset=utf-8",
                              headers=[("Content-Disposition",
                                        f'attachment; filename="squadup-data-{safe_nick}.json"')],
                              compress=False)

        if path == "/api/me" and method == "DELETE":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            listings_ids = [r["id"] for r in conn.execute("SELECT id FROM listings WHERE user_id = ?", (uid,))]
            for lid in listings_ids:
                conn.execute("DELETE FROM player_reviews WHERE listing_id = ?", (lid,))
            conn.execute("DELETE FROM player_reviews WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE user_id = ?)", (uid,))
            conn.execute("DELETE FROM chats WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM applications WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM listings WHERE user_id = ? AND is_seed = 0", (uid,))
            conn.execute("DELETE FROM push_subscriptions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM squads WHERE owner_id = ?", (uid,))
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))
            conn.commit()
            return self._send(200, dict(ok=True, deleted=dict(listings=len(listings_ids))))

        # --- Уведомления (Web Push) ---
        if path == "/api/push/state" and method == "GET":
            pub, _ = vapid_keys(conn)
            subs = 0
            if uid:
                subs = conn.execute("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?",
                                    (uid,)).fetchone()["c"]
            return self._send(200, dict(
                available=PUSH_ENABLED and bool(pub),
                public_key=pub,
                subscribed=subs > 0,
                devices=subs,
                crypto_lib=webpush.CRYPTO_AVAILABLE,
            ))

        if path == "/api/push/subscribe" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            if not PUSH_ENABLED:
                return self._send(503, {"error": "Уведомления недоступны: серверу нужна библиотека cryptography"})
            body = self._json_body()
            endpoint = (body.get("endpoint") or "").strip()
            keys = body.get("keys") or {}
            p256dh, auth = keys.get("p256dh"), keys.get("auth")
            if not (endpoint.startswith("https://") and p256dh and auth):
                return self._send(400, {"error": "Некорректная подписка"})
            conn.execute(
                """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, created_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id,
                       p256dh = excluded.p256dh, auth = excluded.auth, user_agent = excluded.user_agent""",
                (uid, endpoint, p256dh, auth, (self.headers.get("User-Agent") or "")[:200], now_iso()))
            conn.commit()
            devices = conn.execute("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?",
                                   (uid,)).fetchone()["c"]
            return self._send(200, dict(ok=True, devices=devices))

        if path == "/api/push/unsubscribe" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            endpoint = (self._json_body().get("endpoint") or "").strip()
            if endpoint:
                conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ? AND user_id = ?", (endpoint, uid))
            else:
                conn.execute("DELETE FROM push_subscriptions WHERE user_id = ?", (uid,))
            conn.commit()
            return self._send(200, dict(ok=True))

        if path == "/api/push/test" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            unread = unread_count(conn, uid)
            payload = dict(
                title="SQUADUP на связи",
                body="Уведомления работают — мы позовём тебя, когда найдётся тиммейт.",
                url="/?view=chats", badge=unread, tag="squadup-test",
            )
            sent, removed = push_to_user(conn, uid, payload)
            return self._send(200, dict(ok=sent > 0, sent=sent, removed=removed,
                                        devices=conn.execute(
                                            "SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?",
                                            (uid,)).fetchone()["c"]))

        if path == "/api/push/schedule" and method == "POST":
            # Демонстрация фоновой доставки: уведомление придёт через N секунд,
            # даже если приложение закрыто.
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            try:
                delay = max(5, min(300, int(self._json_body().get("delay") or 30)))
            except (TypeError, ValueError):
                delay = 30
            devices = conn.execute("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?",
                                   (uid,)).fetchone()["c"]
            if not devices:
                return self._send(400, {"error": "Сначала включи уведомления на этом устройстве"})
            text = (self._json_body().get("text") or "Проверка фоновой доставки").strip()[:120]

            def later():
                time.sleep(delay)
                conn2 = db_connect()
                try:
                    push_to_user(conn2, uid, dict(
                        title="SQUADUP", body=text, url="/?view=search",
                        badge=unread_count(conn2, uid), tag="squadup-demo"))
                finally:
                    conn2.close()
            threading.Thread(target=later, daemon=True).start()
            return self._send(200, dict(ok=True, delay=delay, devices=devices))

        # --- Discord OAuth ---
        if path == "/api/discord/link-start" and method == "POST":
            if not DISCORD_ENABLED:
                return self._send(403, {"error": "Вход через Discord не настроен на сервере"})
            if not user:
                return self._send(401, {"error": "Сначала войди в SQUADUP"})
            prune_oauth_states()
            state = uuid.uuid4().hex
            with OAUTH_LOCK:
                OAUTH_STATES[state] = dict(created=datetime.now(timezone.utc), link_uid=uid, kind="discord")
            return self._send(200, dict(state=state))

        if path == "/api/auth/discord/login" and method == "GET":
            if not DISCORD_ENABLED:
                return self._redirect("/?discord_error=not_configured")
            state = (query.get("state") or [""])[0]
            with OAUTH_LOCK:
                ticket = OAUTH_STATES.get(state) if state else None
            if ticket and ticket.get("kind") == "discord" and ticket.get("link_uid"):
                link_uid = ticket["link_uid"]  # билет на привязку к текущей анкете
            else:
                # обычный вход через Discord: аккаунт создаётся или находится по discord_id
                link_uid = None
                prune_oauth_states()
                state = uuid.uuid4().hex
                with OAUTH_LOCK:
                    OAUTH_STATES[state] = dict(created=datetime.now(timezone.utc), link_uid=None, kind="discord")
            redirect_uri = DISCORD_REDIRECT_URI or (self.base_url() + "/api/auth/discord/callback")
            import urllib.parse
            qs = urllib.parse.urlencode(dict(response_type="code", client_id=DISCORD_CLIENT_ID,
                                             redirect_uri=redirect_uri, scope="identify",
                                             state=state, prompt="consent"))
            return self._redirect("https://discord.com/oauth2/authorize?" + qs)

        if path == "/api/auth/discord/callback" and method == "GET":
            if not DISCORD_ENABLED:
                return self._redirect("/?discord_error=not_configured")
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [""])[0]
            with OAUTH_LOCK:
                st = OAUTH_STATES.pop(state, None)
            if not st or not code:
                return self._redirect("/?discord_error=state")
            redirect_uri = DISCORD_REDIRECT_URI or (self.base_url() + "/api/auth/discord/callback")
            try:
                tok = http_json("https://discord.com/api/oauth2/token", form=True, data=dict(
                    client_id=DISCORD_CLIENT_ID, client_secret=DISCORD_CLIENT_SECRET,
                    grant_type="authorization_code", code=code, redirect_uri=redirect_uri))
                access = tok.get("access_token")
                if not access:
                    raise RuntimeError("no access_token")
                me = http_json("https://discord.com/api/users/@me",
                               headers={"Authorization": "Bearer " + access})
            except Exception as exc:  # noqa: BLE001
                print("[discord] ошибка обмена токена:", exc, flush=True)
                return self._redirect("/?discord_error=exchange")
            did = str(me.get("id") or "")
            dnick = me.get("global_name") or me.get("username") or ("discord_" + did[:6])
            if not did:
                return self._redirect("/?discord_error=profile")

            if st.get("link_uid"):
                # привязка Discord к уже существующей анкете
                busy = conn.execute("SELECT id FROM users WHERE discord_id = ? AND id <> ?",
                                    (did, st["link_uid"])).fetchone()
                if busy:
                    return self._redirect("/?discord_error=already_linked")
                conn.execute("UPDATE users SET discord_id = ?, discord_username = ? WHERE id = ?",
                             (did, dnick, st["link_uid"]))
                conn.commit()
                return self._redirect("/?discord_linked=1")

            row = conn.execute("SELECT * FROM users WHERE discord_id = ?", (did,)).fetchone()
            if row:
                uid_s, token = row["id"], row["token"]
            else:
                uid_s, token = str(uuid.uuid4()), uuid.uuid4().hex
                nick = dnick[:32]
                base_nick, n = nick, 2
                while conn.execute("SELECT 1 FROM users WHERE nickname = ?", (nick,)).fetchone():
                    nick = f"{base_nick[:29]}_{n}"
                    n += 1
                conn.execute("""INSERT INTO users (id, token, nickname, created_at, discord_id, discord_username)
                                VALUES (?,?,?,?,?,?)""",
                             (uid_s, token, nick, now_iso(), did, dnick))
                conn.commit()
                self.seed_welcome_chats(conn, uid_s)
            return self._redirect("/?token=" + token + "&discord_welcome=1")

        # --- Steam: официальный OpenID 2.0, пароль пользователь вводит только у Steam ---
        # Билет на привязку Steam. Кнопка «Привязать Steam» — обычная ссылка в браузере,
        # а токен входа передаётся заголовком, которого у навигации нет. Поэтому сначала
        # клиент берёт здесь одноразовый билет (10 минут), и только потом уходит на Steam.
        if path == "/api/steam/link-start" and method == "POST":
            if not user:
                return self._send(401, {"error": "Сначала войди в SQUADUP, потом привязывай Steam"})
            prune_oauth_states()
            state = uuid.uuid4().hex
            with OAUTH_LOCK:
                OAUTH_STATES[state] = dict(created=datetime.now(timezone.utc), link_uid=uid, kind="steam")
            return self._send(200, dict(state=state))

        if path == "/api/auth/steam/login" and method == "GET":
            state = (query.get("state") or [""])[0]
            with OAUTH_LOCK:
                ticket = OAUTH_STATES.get(state) if state else None
            if ticket and ticket.get("kind") == "steam" and ticket.get("link_uid"):
                pass  # билет выдан по токену в /api/steam/link-start
            elif user:
                # запасной путь: запрос пришёл с заголовком X-Token (скрипты, старые клиенты)
                prune_oauth_states()
                state = uuid.uuid4().hex
                with OAUTH_LOCK:
                    OAUTH_STATES[state] = dict(created=datetime.now(timezone.utc), link_uid=uid, kind="steam")
            else:
                return self._redirect("/?steam_error=login_required")
            base = self.base_url()
            import urllib.parse
            qs = urllib.parse.urlencode({
                "openid.ns": "http://specs.openid.net/auth/2.0",
                "openid.mode": "checkid_setup",
                "openid.return_to": base + "/api/auth/steam/callback?state=" + state,
                "openid.realm": base,
                "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
                "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
            })
            return self._redirect(STEAM_OPENID_ENDPOINT + "?" + qs)

        if path == "/api/auth/steam/callback" and method == "GET":
            state = (query.get("state") or [""])[0]
            with OAUTH_LOCK:
                st = OAUTH_STATES.pop(state, None)
            # state одноразовый и живёт 10 минут: без него нельзя привязать Steam к чужой анкете
            if not st or st.get("kind") != "steam" or not st.get("link_uid"):
                return self._redirect("/?steam_error=state")
            if (query.get("openid.mode") or [""])[0] == "cancel":
                return self._redirect("/?steam_error=cancelled")
            params = {k: v[0] for k, v in query.items() if k.startswith("openid.")}
            if not params.get("openid.claimed_id"):
                return self._redirect("/?steam_error=cancelled")
            try:
                valid = steam_verify_openid(params)
            except Exception as exc:  # noqa: BLE001
                print("[steam] проверка подписи не удалась:", exc, flush=True)
                return self._redirect("/?steam_error=verify")
            if not valid:
                return self._redirect("/?steam_error=invalid")
            m = STEAM_CLAIMED_ID_RE.match(params.get("openid.claimed_id", ""))
            if not m:
                return self._redirect("/?steam_error=profile")
            steam_id = m.group(1)
            link_uid = st["link_uid"]
            busy = conn.execute("SELECT id FROM users WHERE steam_id = ? AND id <> ?",
                                (steam_id, link_uid)).fetchone()
            if busy:
                return self._redirect("/?steam_error=already_linked")
            prof = steam_fetch_profile(steam_id)
            conn.execute("""UPDATE users SET steam_id = ?, steam_nick = ?, steam_avatar = ?,
                                           steam_linked_at = ? WHERE id = ?""",
                         (steam_id, prof["nick"], prof["avatar"], now_iso(), link_uid))
            conn.commit()
            return self._redirect("/?steam_linked=1")

        if path == "/api/unlink-steam" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            conn.execute("""UPDATE users SET steam_id = NULL, steam_nick = NULL, steam_avatar = NULL,
                                           steam_linked_at = NULL WHERE id = ?""", (uid,))
            conn.commit()
            return self._send(200, dict(ok=True))

        if path == "/api/steam/refresh" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            sid = user["steam_id"] if "steam_id" in user.keys() else None
            if not sid:
                return self._send(400, {"error": "Steam не привязан"})
            prof = steam_fetch_profile(sid)
            if not prof["nick"] and not prof["avatar"]:
                return self._send(200, dict(ok=False, nick="", avatar="",
                                            message="Steam не отдал профиль — обычно это значит, "
                                                    "что профиль закрыт или Steam ограничил запросы. "
                                                    "Привязка при этом сохраняется."))
            conn.execute("UPDATE users SET steam_nick = ?, steam_avatar = ? WHERE id = ?",
                         (prof["nick"], prof["avatar"], uid))
            conn.commit()
            return self._send(200, dict(ok=True, nick=prof["nick"], avatar=prof["avatar"]))

        if path == "/api/steam/visibility" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            public = 1 if body.get("public") else 0
            conn.execute("UPDATE users SET steam_public = ? WHERE id = ?", (public, uid))
            conn.commit()
            return self._send(200, dict(ok=True, public=bool(public)))

        if path == "/api/unlink-discord" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            conn.execute("UPDATE users SET discord_id = NULL, discord_username = NULL WHERE id = ?", (uid,))
            conn.commit()
            return self._send(200, dict(ok=True))

        if path == "/api/me" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            listing_row = conn.execute("SELECT * FROM listings WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                                       (uid,)).fetchone()
            unread = unread_count(conn, uid) + unread_groups_total(conn, uid)
            apps = conn.execute("""SELECT a.*, s.name AS squad_name, s.tag AS squad_tag FROM applications a
                                   LEFT JOIN squads s ON s.id = a.squad_id
                                   WHERE a.user_id = ? ORDER BY a.id DESC""", (uid,)).fetchall()
            keys = user.keys()
            return self._send(200, dict(
                user_id=uid, nickname=user["nickname"], unread=unread,
                discord=dict(linked=bool(user["discord_id"]) if "discord_id" in keys else False,
                             username=(user["discord_username"] or "") if "discord_username" in keys else ""),
                steam=dict(linked=bool(user["steam_id"]) if "steam_id" in keys else False,
                           nick=(user["steam_nick"] or "") if "steam_nick" in keys else "",
                           avatar=(user["steam_avatar"] or "") if "steam_avatar" in keys else "",
                           profile_loaded=bool((user["steam_nick"] or user["steam_avatar"])
                                               if ("steam_nick" in keys and "steam_avatar" in keys) else False),
                           public=bool(user["steam_public"]) if "steam_public" in keys else True,
                           profile_url=("https://steamcommunity.com/profiles/" + user["steam_id"])
                           if ("steam_id" in keys and user["steam_id"]) else ""),
                discord_enabled=DISCORD_ENABLED,
                listing=row_to_listing(listing_row, uid, full=True, conn=conn) if listing_row else None,
                applications=[dict(id=a["id"], squad_id=a["squad_id"], squad_name=a["squad_name"],
                                   squad_tag=a["squad_tag"], message=a["message"], status=a["status"],
                                   created_at=a["created_at"]) for a in apps],
            ))

        if path == "/api/stats" and method == "GET":
            online = conn.execute("SELECT COUNT(*) AS c FROM listings WHERE online = 1").fetchone()["c"]
            total = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
            squads = conn.execute("SELECT COUNT(*) AS c FROM squads WHERE filled < size").fetchone()["c"]
            games = len(GAMES)
            return self._send(200, dict(online=online, total=total, squads=squads, games=games))

        # --- анкеты игроков ---
        if path == "/api/players" and method == "GET":
            rows = conn.execute("SELECT * FROM listings WHERE hidden = 0 ORDER BY id").fetchall()
            items = [row_to_listing(r, uid, conn=conn) for r in rows]
            items = [i for i in items if not (query.get("exclude_me") and i["is_me"])]
            if uid:
                # прячем анкеты заблокированных (в обе стороны) — для этого нужны id владельцев
                blocked = blocked_ids(conn, uid)
                if blocked:
                    owners = {r["id"]: r["user_id"] for r in
                              conn.execute("SELECT id, user_id FROM listings WHERE hidden = 0").fetchall()}
                    items = [i for i in items if owners.get(i["id"]) not in blocked]
            items = self.apply_filters(items, query)
            sort = (query.get("sort") or ["rating"])[0]
            if sort == "online":
                items.sort(key=lambda x: (-x["online"], -x["rating"]))
            elif sort == "new":
                items.sort(key=lambda x: x["created_at"], reverse=True)
            elif sort == "hours":
                items.sort(key=lambda x: -x["hours"])
            else:
                items.sort(key=lambda x: (-x["rating"], -x["reviews_count"]))
            return self._send(200, dict(count=len(items), items=items))

        m = re.match(r"^/api/players/(\d+)$", path)
        if m and method == "GET":
            row = conn.execute("SELECT * FROM listings WHERE id = ?", (int(m.group(1)),)).fetchone()
            if not row:
                return self._send(404, {"error": "Анкета не найдена"})
            try:
                if int(m.group(1)) != 0 and row["hidden"] and row["user_id"] != uid:
                    return self._send(404, {"error": "Анкета скрыта модерацией"})
            except (KeyError, TypeError):
                pass
            out = row_to_listing(row, uid, full=True, conn=conn)
            out["reports_count"] = row["reports_count"] if "reports_count" in row.keys() else 0
            return self._send(200, out)

        m = re.match(r"^/api/players/(\d+)/review$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            lid = int(m.group(1))
            listing = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
            if not listing:
                return self._send(404, {"error": "Анкета не найдена"})
            if listing["user_id"] == uid:
                return self._send(400, {"error": "Нельзя оставить отзыв самому себе"})
            body = self._json_body()
            try:
                rating = int(body.get("rating"))
            except (TypeError, ValueError):
                rating = 0
            if rating < 1 or rating > 5:
                return self._send(400, {"error": "Поставь оценку от 1 до 5"})
            text = (body.get("text") or "").strip()[:400]
            base_r = listing["rating"] or 5.0
            base_c = listing["reviews_count"] or 0
            prev = conn.execute("SELECT * FROM player_reviews WHERE listing_id = ? AND user_id = ?",
                                (lid, uid)).fetchone()
            if prev:
                new_c = base_c
                new_r = (base_r * base_c - prev["rating"] + rating) / base_c if base_c else float(rating)
                conn.execute("UPDATE player_reviews SET rating = ?, text = ?, created_at = ? WHERE id = ?",
                             (rating, text, now_iso(), prev["id"]))
            else:
                new_c = base_c + 1
                new_r = (base_r * base_c + rating) / new_c
                conn.execute("""INSERT INTO player_reviews (listing_id, user_id, author, rating, text, created_at)
                                VALUES (?,?,?,?,?,?)""",
                             (lid, uid, user["nickname"], rating, text, now_iso()))
            conn.execute("UPDATE listings SET rating = ?, reviews_count = ? WHERE id = ?",
                         (round(new_r, 2), new_c, lid))
            conn.commit()
            row = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
            return self._send(200, dict(ok=True, updated=bool(prev),
                                        listing=row_to_listing(row, uid, full=True, conn=conn)))

        # --- «Ищу сейчас» ---
        if path == "/api/looking" and method == "GET":
            cutoff = iso_cutoff(LOOKING_WINDOW_MIN)
            rows = conn.execute(
                "SELECT * FROM listings WHERE looking_at IS NOT NULL AND looking_at >= ? ORDER BY looking_at DESC",
                (cutoff,)).fetchall()
            items = [row_to_listing(r, uid, conn=conn) for r in rows]
            game = (query.get("game") or [""])[0]
            region = (query.get("region") or [""])[0]
            if game:
                items = [i for i in items if any(g["game_id"] == game for g in i["games"])]
            if region:
                items = [i for i in items if i["region"] == region]
            me_looking, me_since = False, None
            if uid:
                mine = conn.execute("SELECT * FROM listings WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                                    (uid,)).fetchone()
                if mine and mine["looking_at"] and mine["looking_at"] >= cutoff:
                    me_looking, me_since = True, mine["looking_at"]
            return self._send(200, dict(count=len(items), window_minutes=LOOKING_WINDOW_MIN,
                                        me_looking=me_looking, me_since=me_since, items=items))

        if path == "/api/looking" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            mine = conn.execute("SELECT * FROM listings WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                                (uid,)).fetchone()
            if not mine:
                return self._send(400, {"error": "Сначала заполни анкету — иначе тебя не увидят",
                                        "need_listing": True})
            on = bool(self._json_body().get("on"))
            if on:
                conn.execute("UPDATE listings SET looking_at = ?, online = 1, last_seen = ? WHERE id = ?",
                             (now_iso(), now_iso(), mine["id"]))
            else:
                conn.execute("UPDATE listings SET looking_at = NULL WHERE id = ?", (mine["id"],))
            conn.commit()
            return self._send(200, dict(ok=True, looking=on,
                                        since=now_iso() if on else None))

        if path == "/api/listing" and method == "PUT":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            nick = (body.get("nick") or user["nickname"]).strip()[:32]
            games = [g for g in (body.get("games") or []) if g.get("game_id") in GAME_BY_ID][:4]
            if not games:
                return self._send(400, {"error": "Выберите хотя бы одну игру"})
            existing = conn.execute("SELECT id FROM listings WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                                    (uid,)).fetchone()
            platforms = [p for p in (body.get("platforms") or []) if p in PLATFORM_LABELS]
            if not platforms:
                platforms = ["pc"]
            languages = (body.get("languages") or ["Русский"])[:6]
            payload = dict(
                nick=nick,
                age=int(body.get("age") or 18),
                region=body.get("region") if body.get("region") in REGION_BY_ID else "eu",
                platforms=json.dumps(platforms, ensure_ascii=False),
                languages=json.dumps(languages, ensure_ascii=False),
                skill=int(body.get("skill") or 3),
                mic=1 if body.get("mic") else 0,
                vibe=body.get("vibe") if body.get("vibe") in VIBES else "chill",
                schedule=json.dumps([s for s in (body.get("schedule") or []) if s in SCHEDULE_SLOTS] or ["Вечер 18–24"], ensure_ascii=False),
                about=(body.get("about") or "")[:600],
                games=json.dumps(games, ensure_ascii=False),
                contact=(body.get("contact") or "").strip()[:60],
            )
            if existing:
                sets = ", ".join(f"{k} = ?" for k in payload)
                conn.execute(f"UPDATE listings SET {sets}, online = 1, last_seen = ? WHERE id = ?",
                             (*payload.values(), now_iso(), existing["id"]))
                lid = existing["id"]
            else:
                cur = conn.execute(
                    """INSERT INTO listings (user_id,nick,age,region,platforms,languages,skill,mic,vibe,schedule,
                       about,games,rating,reviews_count,hours,online,verified,last_seen,reviews,is_seed,contact,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, nick, payload["age"], payload["region"], payload["platforms"], payload["languages"],
                     payload["skill"], payload["mic"], payload["vibe"], payload["schedule"], payload["about"],
                     payload["games"], 5.0, 0, sum(int(g.get("hours") or 0) for g in games), 1, 0,
                     now_iso(), json.dumps([], ensure_ascii=False), 0, payload["contact"], now_iso()))
                lid = cur.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM listings WHERE id = ?", (lid,)).fetchone()
            return self._send(200, dict(ok=True, listing=row_to_listing(row, uid, full=True, conn=conn)))

        # --- приглашения / чаты ---
        if path == "/api/invite" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            try:
                listing_id = int(body.get("listing_id"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "Некорректная анкета"})
            listing = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
            if not listing:
                return self._send(404, {"error": "Анкета не найдена"})
            text = (body.get("message") or "Привет! Ищу тиммейтов, давай сыграем вместе?").strip()[:500]
            peer_uid = listing["user_id"]
            if peer_uid == uid:
                return self._send(400, {"error": "Это твоя анкета"})
            if is_blocked_between(conn, uid, peer_uid):
                return self._send(403, {"error": "Переписка с этим игроком недоступна"})
            if peer_uid:
                # реальный игрок: ищем уже существующий диалог в любом направлении
                chat = find_chat(conn, uid, peer_uid)
            else:
                # демо-анкета: диалог только с этой анкетой
                chat = conn.execute("SELECT * FROM chats WHERE user_id = ? AND listing_id = ?",
                                    (uid, listing_id)).fetchone()
            if not chat:
                cur = conn.execute(
                    """INSERT INTO chats (user_id, listing_id, peer_nick, peer_user_id, unread, unread_b,
                                            requested, requester_id, created_at, updated_at)
                       VALUES (?,?,?,?,0,0,?,?,?,?)""",
                    (uid, listing_id, listing["nick"], peer_uid, 1, uid, now_iso(), now_iso()))
                chat_id = cur.lastrowid
                initiator_is_me = True
            else:
                chat_id = chat["id"]
                initiator_is_me = (chat["user_id"] == uid)
            conn.execute("INSERT INTO messages (chat_id, sender, text, kind, meta, created_at) "
                         "VALUES (?,?,?,?,?,?)",
                         (chat_id, "me" if initiator_is_me else "peer", text, "text", "{}", now_iso()))
            if initiator_is_me:
                conn.execute("UPDATE chats SET updated_at = ?, unread_b = unread_b + 1 WHERE id = ?",
                             (now_iso(), chat_id))
            else:
                conn.execute("UPDATE chats SET updated_at = ?, unread = unread + 1 WHERE id = ?",
                             (now_iso(), chat_id))
            conn.commit()
            if peer_uid:
                push_async(peer_uid, dict(
                    title="Новое сообщение",
                    body=f"{user['nickname']}: {text[:120]}", url="/?view=chats",
                    tag=f"chat-{chat_id}", badge=unread_count(conn, peer_uid)))
            return self._send(200, dict(ok=True, chat_id=chat_id, peer_nick=listing["nick"]))

        if path == "/api/chats" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            rows = conn.execute(
                "SELECT * FROM chats WHERE user_id = ? OR peer_user_id = ? ORDER BY updated_at DESC",
                (uid, uid)).fetchall()
            blocked = blocked_ids(conn, uid)
            chats = []
            for c in rows:
                peer_uid, peer_nick, is_initiator, my_unread = chat_partner(conn, c, uid)
                if peer_uid and peer_uid in blocked:
                    continue  # диалоги с заблокированными не показываем
                last = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                                    (c["id"],)).fetchone()
                listing = conn.execute("SELECT games FROM listings WHERE id = ?", (c["listing_id"],)).fetchone()
                first_game = None
                game_id = None
                if listing and listing["games"]:
                    gd = json.loads(listing["games"])
                    if gd and gd[0]["game_id"] in GAME_BY_ID:
                        gg = GAME_BY_ID[gd[0]["game_id"]]
                        first_game = dict(short=gg["short"])
                        game_id = gg["id"]
                # роли сообщений клиенту: 'me' — это я
                last_sender = None
                last_text = ""
                if last:
                    last_sender = last["sender"] if is_initiator else ("peer" if last["sender"] == "me" else "me")
                    last_text = "Сообщение удалено" if last["deleted"] else last["text"]
                # «печатает»: отметка живёт 8 секунд, роли такие же, как у сообщений
                peer_typing_at = (c["typing_b"] if is_initiator else c["typing_a"]) if "typing_b" in c.keys() else None
                peer_typing = bool(peer_typing_at and peer_typing_at >= iso_cutoff(8 / 60))
                peer_online, peer_last_seen, peer_avatar = peer_presence(conn, peer_uid, c["listing_id"])
                chats.append(dict(
                    id=c["id"], listing_id=c["listing_id"], peer_nick=peer_nick,
                    peer_user_id=(peer_uid[:8] if peer_uid else None),
                    unread=my_unread, game=first_game, game_id=game_id,
                    last_message=last_text,
                    last_sender=last_sender,
                    typing=peer_typing,
                    online=peer_online,
                    last_seen=peer_last_seen,
                    avatar=peer_avatar,
                    updated_at=c["updated_at"],
                ))
            return self._send(200, dict(items=chats))

        m = re.match(r"^/api/chats/(\d+)/messages$", path)
        if m:
            chat_id = int(m.group(1))
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                (chat_id, uid, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            _, peer_nick, is_initiator, _ = chat_partner(conn, chat, uid)
            peer_uid = chat["peer_user_id"] if is_initiator else chat["user_id"]
            if peer_uid and is_blocked_between(conn, uid, peer_uid):
                return self._send(403, {"error": "Переписка с этим игроком недоступна"})
            if method == "GET":
                after = qint(query, "after", 0, lo=0)
                full = (query.get("all") or [""])[0] in ("1", "true")
                if full:
                    after = 0
                if after <= 0:
                    # открыли диалог — отдаём всю переписку (для поиска и перехода к сообщению)
                    rows = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id LIMIT 500",
                                        (chat_id,)).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM messages WHERE chat_id = ? AND id > ? ORDER BY id",
                                        (chat_id, after)).fetchall()
                # изменения уже загруженных сообщений: правки и удаления (для опроса)
                changed_rows = []
                if after > 0:
                    since = (query.get("since") or [""])[0] or now_iso(-10)
                    changed_rows = conn.execute(
                        """SELECT * FROM messages WHERE chat_id = ? AND id <= ?
                           AND ((edited_at IS NOT NULL AND edited_at >= ?)
                                OR (deleted_at IS NOT NULL AND deleted_at >= ?))
                           ORDER BY id LIMIT 100""",
                        (chat_id, after, since, since)).fetchall()
                # ответы: подтягиваем цитаты одним запросом, чтобы не дёргать базу на каждое сообщение
                quotes = {}
                ids = [r["reply_to"] for r in list(rows) + list(changed_rows) if r["reply_to"]]
                if ids:
                    marks = ",".join("?" * len(ids))
                    for q in conn.execute(f"SELECT id, sender, text, deleted FROM messages WHERE id IN ({marks})", ids):
                        quotes[q["id"]] = q
                # реакции на сообщения (текстовые, без эмодзи)
                reacts = {}
                all_ids = [r["id"] for r in list(rows) + list(changed_rows)]
                if all_ids:
                    marks = ",".join("?" * len(all_ids))
                    for rr in conn.execute(
                            f"SELECT message_id, value, COUNT(*) AS c, "
                            f"MAX(CASE WHEN user_id = ? THEN 1 ELSE 0 END) AS me FROM reactions "
                            f"WHERE chat_kind = 'dm' AND chat_id = ? AND message_id IN ({marks}) "
                            f"GROUP BY message_id, value ORDER BY MIN(created_at)", [uid, chat_id] + all_ids):
                        reacts.setdefault(rr["message_id"], []).append(
                            dict(value=rr["value"], count=rr["c"], mine=bool(rr["me"])))
                peer_read_at = (chat["read_b"] if is_initiator else chat["read_a"]) if "read_b" in chat.keys() else None
                my_read_at = (chat["read_a"] if is_initiator else chat["read_b"]) if "read_a" in chat.keys() else None
                peer_typing_at = (chat["typing_b"] if is_initiator else chat["typing_a"]) if "typing_b" in chat.keys() else None

                def to_item(r):
                    sender = r["sender"] if is_initiator else ("peer" if r["sender"] == "me" else "me")
                    quote = None
                    q = quotes.get(r["reply_to"]) if r["reply_to"] else None
                    if q is not None:
                        q_sender = q["sender"] if is_initiator else ("peer" if q["sender"] == "me" else "me")
                        who = (user["nickname"] if q_sender == "me" else peer_nick) or "Игрок"
                        quote = dict(id=q["id"], nick=who,
                                     text=("Сообщение удалено" if q["deleted"] else (q["text"] or ""))[:160])
                    meta = {}
                    if "meta" in r.keys() and r["meta"]:
                        try:
                            meta = json.loads(r["meta"])
                        except Exception:
                            meta = {}
                    kind = (r["kind"] if "kind" in r.keys() and r["kind"] else "text")
                    item = dict(
                        kind=kind, meta=meta,
                        pinned=bool(r["pinned"]) if "pinned" in r.keys() else False,
                        id=r["id"], sender=sender,
                        text="" if r["deleted"] else r["text"],
                        created_at=r["created_at"],
                        deleted=bool(r["deleted"]),
                        edited_at=(r["edited_at"] if "edited_at" in r.keys() else None),
                        edited=bool("edited_at" in r.keys() and r["edited_at"]),
                        read=bool(sender == "me" and peer_read_at and peer_read_at >= r["created_at"]),
                        reply_to=quote,
                        reactions=reacts.get(r["id"], []),
                    )
                    if item["kind"] == "invite":
                        item["invite"] = dict(meta)
                    if item["kind"] == "lfg":
                        item["lfg"] = dict(meta)
                    return item

                items = [to_item(r) for r in rows]
                changed = [to_item(r) for r in changed_rows if r["id"] not in {i["id"] for i in items}]
                peer_online, peer_last_seen, peer_avatar = peer_presence(conn, peer_uid, chat["listing_id"])
                return self._send(200, dict(
                    items=items, peer_nick=peer_nick,
                    peer_user_id=(peer_uid[:8] if peer_uid else None),
                    is_demo=not peer_uid,
                    online=peer_online, last_seen=peer_last_seen, avatar=peer_avatar,
                    typing=bool(peer_typing_at and peer_typing_at >= iso_cutoff(8 / 60)),
                    my_read_at=my_read_at, peer_read_at=peer_read_at,
                    changed=changed))
            if method == "POST":
                if peer_uid and is_blocked_between(conn, uid, peer_uid):
                    return self._send(403, {"error": "Переписка с этим игроком недоступна"})
                body = self._json_body()
                text = (body.get("text") or "").strip()[:800]
                kind = (body.get("kind") or "text")[:12]
                meta = body.get("meta") or {}
                if kind not in ("text", "media", "invite", "lfg"):
                    return self._send(400, {"error": "Неизвестный тип сообщения"})
                if kind == "media":
                    clean = []
                    for att in (meta.get("attachments") or [])[:6]:
                        url = str(att.get("url") or "")
                        if not url.startswith("/uploads/"):
                            continue
                        clean.append(dict(url=url, name=str(att.get("name") or "файл")[:80],
                                          type=str(att.get("type") or "")[:60], size=int(att.get("size") or 0),
                                          is_image=bool(att.get("is_image")),
                                          is_video=bool(att.get("is_video"))))
                    if not clean:
                        return self._send(400, {"error": "К сообщению не приложен файл"})
                    meta = dict(meta)
                    meta["attachments"] = clean
                if not text and kind != "media":
                    return self._send(400, {"error": "Пустое сообщение"})
                # ответ на сообщение: принимаем только сообщение из этого же чата
                reply_to = body.get("reply_to")
                reply_to = int(reply_to) if str(reply_to or "").isdigit() else None
                if reply_to:
                    same = conn.execute("SELECT 1 FROM messages WHERE id = ? AND chat_id = ?",
                                        (reply_to, chat_id)).fetchone()
                    if not same:
                        reply_to = None
                internal_sender = "me" if is_initiator else "peer"
                cur = conn.execute(
                    "INSERT INTO messages (chat_id, sender, text, kind, meta, reply_to, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (chat_id, internal_sender, text, kind, json.dumps(meta, ensure_ascii=False),
                     reply_to, now_iso()))
                # своё непрочитанное сбрасываем (я прочитал, раз пишу), собеседнику — +1
                if is_initiator:
                    if peer_uid:
                        conn.execute("UPDATE chats SET updated_at = ?, unread = 0, unread_b = unread_b + 1 WHERE id = ?",
                                     (now_iso(), chat_id))
                    else:
                        conn.execute("UPDATE chats SET updated_at = ?, unread = 0 WHERE id = ?", (now_iso(), chat_id))
                else:
                    if peer_uid:
                        conn.execute("UPDATE chats SET updated_at = ?, unread_b = 0, unread = unread + 1 WHERE id = ?",
                                     (now_iso(), chat_id))
                    else:
                        conn.execute("UPDATE chats SET updated_at = ?, unread_b = 0 WHERE id = ?", (now_iso(), chat_id))
                conn.commit()
                # уведомляем собеседника, если это реальный аккаунт
                if peer_uid:
                    push_async(peer_uid, dict(
                        title=f"{user['nickname']} написал", body=text[:140],
                        url="/?view=chats", badge=unread_count(conn, peer_uid), tag=f"chat-{chat_id}"))
                return self._send(200, dict(ok=True, id=cur.lastrowid))

        m = re.match(r"^/api/chats/(\d+)/search$", path)
        if m and method == "GET":
            chat_id = int(m.group(1))
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                (chat_id, uid, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            q = (query.get("q") or [""])[0].strip()[:80]
            if len(q) < 2:
                return self._send(200, dict(items=[]))
            _, peer_nick, is_initiator, _ = chat_partner(conn, chat, uid)
            like = "%" + q.replace("%", "").replace("_", "") + "%"
            rows = conn.execute(
                """SELECT id, sender, text, created_at FROM messages
                   WHERE chat_id = ? AND deleted = 0 AND text LIKE ? COLLATE NOCASE
                   ORDER BY id DESC LIMIT 50""", (chat_id, like)).fetchall()
            items = []
            for r in rows:
                mine = (r["sender"] == "me") == is_initiator
                items.append(dict(id=r["id"], text=r["text"][:160],
                                  nick=(user["nickname"] if mine else peer_nick),
                                  created_at=r["created_at"]))
            return self._send(200, dict(items=items, q=q))

        m = re.match(r"^/api/chats/(\d+)/read$", path)
        if m and method == "POST":
            chat_id = int(m.group(1))
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                (chat_id, uid, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            if chat["user_id"] == uid:
                # отметка времени нужна для статуса «прочитано» у собеседника
                conn.execute("UPDATE chats SET unread = 0, read_a = ? WHERE id = ?", (now_iso(), chat_id))
            else:
                conn.execute("UPDATE chats SET unread_b = 0, read_b = ? WHERE id = ?", (now_iso(), chat_id))
            conn.commit()
            return self._send(200, dict(ok=True))

        m = re.match(r"^/api/chats/(\d+)/typing$", path)
        if m and method == "POST":
            chat_id = int(m.group(1))
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                (chat_id, uid, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            col = "typing_a" if chat["user_id"] == uid else "typing_b"
            conn.execute(f"UPDATE chats SET {col} = ? WHERE id = ?", (now_iso(), chat_id))
            conn.commit()
            return self._send(200, dict(ok=True))

        m = re.match(r"^/api/chats/(\d+)/messages/(\d+)/(edit|delete)$", path)
        if m and method == "POST":
            chat_id, msg_id, action = int(m.group(1)), int(m.group(2)), m.group(3)
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                (chat_id, uid, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            row = conn.execute("SELECT * FROM messages WHERE id = ? AND chat_id = ?", (msg_id, chat_id)).fetchone()
            if not row:
                return self._send(404, {"error": "Сообщение не найдено"})
            is_initiator = chat["user_id"] == uid
            mine = (row["sender"] == "me") == is_initiator   # роли в базе относительные
            if not mine:
                return self._send(403, {"error": "Можно менять только свои сообщения"})
            if row["deleted"]:
                return self._send(400, {"error": "Сообщение уже удалено"})
            if action == "delete":
                conn.execute("UPDATE messages SET deleted = 1, deleted_at = ?, text = '', reply_to = NULL "
                             "WHERE id = ?", (now_iso(), msg_id))
                conn.commit()
                return self._send(200, dict(ok=True, deleted=True))
            body = self._json_body()
            text = (body.get("text") or "").strip()[:800]
            if not text:
                return self._send(400, {"error": "Пустое сообщение"})
            conn.execute("UPDATE messages SET text = ?, edited_at = ? WHERE id = ?", (text, now_iso(), msg_id))
            conn.commit()
            return self._send(200, dict(ok=True, edited=True, text=text))

        m = re.match(r"^/api/chats/(\d+)/simulate-reply$", path)
        if m and method == "POST":
            # Демо-режим: собеседник «отвечает» заготовленной фразой.
            chat_id = int(m.group(1))
            chat = conn.execute("SELECT * FROM chats WHERE id = ? AND user_id = ?", (chat_id, uid)).fetchone()
            if not chat:
                return self._send(404, {"error": "Чат не найден"})
            if chat["peer_user_id"]:
                # с реальным игроком автоответов нет — ждём его самого
                return self._send(200, dict(ok=False, reason="real_player"))
            last = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                                (chat_id,)).fetchone()
            if not last or last["sender"] != "me":
                return self._send(200, dict(ok=False, reason="no pending message"))
            rnd = random.Random(last["id"] * 7919)
            text = rnd.choice(REPLIES)
            conn.execute("INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?,?,?,?)",
                         (chat_id, "peer", text, now_iso()))
            conn.execute("UPDATE chats SET updated_at = ?, unread = unread + 1 WHERE id = ?", (now_iso(), chat_id))
            conn.commit()
            push_async(uid, dict(
                title=f"{chat['peer_nick']} ответил",
                body=text[:140], url="/?view=chats",
                badge=unread_count(conn, uid), tag=f"chat-{chat_id}"))
            return self._send(200, dict(ok=True))

        # --- сквады ---
        if path == "/api/squads" and method == "GET":
            rows = conn.execute("SELECT * FROM squads ORDER BY (size - filled) DESC, id").fetchall()
            applied = set()
            if uid:
                applied = {r["squad_id"] for r in conn.execute(
                    "SELECT squad_id FROM applications WHERE user_id = ?", (uid,)).fetchall()}
            items = [row_to_squad(r, uid, applied) for r in rows]
            gid = (query.get("game") or [None])[0]
            region = (query.get("region") or [None])[0]
            if gid:
                items = [i for i in items if i["game_id"] == gid]
            if region:
                items = [i for i in items if i["region"] == region]
            return self._send(200, dict(count=len(items), items=items))

        if path == "/api/squads" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            gid = body.get("game_id")
            if gid not in GAME_BY_ID:
                return self._send(400, {"error": "Выберите игру"})
            name = (body.get("name") or "").strip()[:40]
            if not name:
                return self._send(400, {"error": "Введите название сквада"})
            size = max(2, min(10, int(body.get("size") or 5)))
            need = [r for r in (body.get("need") or [])][:6]
            cur = conn.execute(
                """INSERT INTO squads (name,tag,game_id,mode,region,language,size,filled,need,min_rank,mic,schedule,
                   about,captain,owner_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, (body.get("tag") or name[:4]).upper()[:5], gid,
                 body.get("mode") if body.get("mode") in MODE_LABELS else GAME_BY_ID[gid]["modes"][0],
                 body.get("region") if body.get("region") in REGION_BY_ID else "eu",
                 (body.get("language") or "Русский")[:40], size, 1,
                 json.dumps(need, ensure_ascii=False), (body.get("min_rank") or "Любой")[:40],
                 1 if body.get("mic") else 0, (body.get("schedule") or "Вечер 18–24")[:80],
                 (body.get("about") or "")[:600], user["nickname"], uid, now_iso()))
            conn.commit()
            row = conn.execute("SELECT * FROM squads WHERE id = ?", (cur.lastrowid,)).fetchone()
            return self._send(200, dict(ok=True, squad=row_to_squad(row, uid, set())))

        m = re.match(r"^/api/squads/(\d+)/apply$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            squad_id = int(m.group(1))
            squad = conn.execute("SELECT * FROM squads WHERE id = ?", (squad_id,)).fetchone()
            if not squad:
                return self._send(404, {"error": "Сквад не найден"})
            body = self._json_body()
            exists = conn.execute("SELECT id FROM applications WHERE squad_id = ? AND user_id = ?",
                                  (squad_id, uid)).fetchone()
            if exists:
                return self._send(200, dict(ok=True, already=True))
            conn.execute("INSERT INTO applications (squad_id, user_id, message, created_at) VALUES (?,?,?,?)",
                         (squad_id, uid, (body.get("message") or "")[:400], now_iso()))
            conn.commit()
            if squad["owner_id"] and squad["owner_id"] != uid:
                push_async(squad["owner_id"], dict(
                    title=f"Заявка в сквад «{squad['name']}»",
                    body=(body.get("message") or "Игрок хочет присоединиться")[:140],
                    url="/?view=squads", tag=f"squad-{squad_id}"))
            return self._send(200, dict(ok=True))

        m = re.match(r"^/api/users/([^/]+)/card$", path)
        if m and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            import urllib.parse
            key = urllib.parse.unquote(m.group(1))
            target = resolve_user_key(conn, key)
            if not target:
                return self._send(404, {"error": "Игрок не найден"})
            card = user_card(conn, target)
            listing = conn.execute("SELECT * FROM listings WHERE user_id = ? ORDER BY id LIMIT 1",
                                   (target,)).fetchone()
            if listing is not None:
                info = row_to_listing(listing, uid, conn=conn)
                card["listing_id"] = info["id"]
                card["rating"] = info["rating"]
                card["reviews_count"] = info["reviews_count"]
                card["region_label"] = info["region_label"]
                card["mic"] = info["mic"]
                card["games"] = [dict(id=g["game_id"], name=g["name"], short=g["short"], rank=g["rank"])
                                 for g in info["games"][:4]]
                card["tags"] = player_tags(conn, listing)
                card["about"] = (info["about"] or "")[:200]
                card["is_meaningful"] = True
            else:
                card.update(dict(listing_id=None, rating=None, reviews_count=0, region_label="",
                                 mic=False, games=[], tags=[], about="", is_meaningful=False))
            blocked = is_blocked_between(conn, uid, target)
            card["blocked"] = bool(blocked)
            card["is_me"] = (target == uid)
            return self._send(200, dict(card=card))

        # ==================== загрузка медиа (1.10) ====================
        if path == "/api/uploads" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            ctype = self.headers.get("Content-Type") or ""
            if "multipart/form-data" not in ctype:
                return self._send(400, {"error": "Нужен файл в форме multipart/form-data"})
            boundary = ""
            for kv in ctype.split(";"):
                k, _, v = kv.strip().partition("=")
                if k.lower() == "boundary":
                    boundary = v.strip().strip('"')
            length = int(self.headers.get("Content-Length") or 0)
            limit = MAX_UPLOAD_MB * 1024 * 1024
            if length <= 0:
                return self._send(400, {"error": "Пустой запрос"})
            if length > limit:
                return self._send(413, {"error": f"Файл больше {MAX_UPLOAD_MB} МБ"})
            body = self.rfile.read(length)
            parts = parse_multipart(body, boundary)
            part = parts.get("file") or (list(parts.values())[0] if parts else None)
            if not part or not part["data"]:
                return self._send(400, {"error": "Файл не пришёл"})
            if len(part["data"]) > limit:
                return self._send(413, {"error": f"Файл больше {MAX_UPLOAD_MB} МБ"})
            shown_name = (part["filename"] or "файл").strip()[:80] or "файл"
            ext = os.path.splitext(safe_filename(shown_name))[1].lower()[:8]
            stored = f"{uuid.uuid4().hex[:16]}{ext}"
            with open(os.path.join(UPLOADS_DIR, stored), "wb") as fh:
                fh.write(part["data"])
            ftype = part["ctype"] or "application/octet-stream"
            is_image = ftype.startswith("image/")
            is_video = ftype.startswith("video/")
            return self._send(200, dict(ok=True, url="/uploads/" + stored, name=shown_name,
                                        type=ftype, size=len(part["data"]),
                                        is_image=is_image, is_video=is_video))

        # ==================== общий поиск (1.10) ====================
        if path == "/api/search" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            q = (query.get("q") or [""])[0].strip()
            from_nick = (query.get("from") or [""])[0].strip()
            game_id = (query.get("game") or [""])[0].strip()
            what = (query.get("kind") or ["all"])[0]
            # «from:Ник game:cs2» можно писать прямо в строке поиска
            for token in q.split():
                if token.lower().startswith("from:"):
                    from_nick = token[5:]
                elif token.lower().startswith("game:"):
                    game_id = token[5:]
            q_clean = " ".join(t for t in q.split() if not t.lower().startswith(("from:", "game:")))
            like = "%" + q_clean + "%"
            wants = lambda k: what in ("all", k)   # noqa: E731
            out = dict(messages=[], players=[], files=[], links=[])
            if q_clean and wants("messages"):
                rows = conn.execute(
                    """SELECT m.*, c.id AS chat_id FROM messages m JOIN chats c ON c.id = m.chat_id
                       WHERE (c.user_id = ? OR c.peer_user_id = ?) AND m.deleted = 0 AND m.text LIKE ?
                       ORDER BY m.id DESC LIMIT 20""", (uid, uid, like)).fetchall()
                for r in rows:
                    _, peer_nick, is_initiator, _ = chat_partner(conn, conn.execute(
                        "SELECT * FROM chats WHERE id = ?", (r["chat_id"],)).fetchone(), uid)
                    sender_uid = (conn.execute("SELECT user_id, peer_user_id FROM chats WHERE id = ?",
                                               (r["chat_id"],)).fetchone())
                    sender = user["nickname"] if r["sender"] == ("me" if is_initiator else "peer") else peer_nick
                    if from_nick and from_nick.lower() not in (sender or "").lower():
                        continue
                    out["messages"].append(dict(chat_kind="dm", chat_id=r["chat_id"], chat_title=peer_nick,
                                                id=r["id"], text=(r["text"] or "")[:200], nick=sender,
                                                created_at=r["created_at"]))
                grows = conn.execute(
                    """SELECT gm.*, g.id AS gid FROM group_messages gm
                       JOIN group_chats g ON g.id = gm.chat_id
                       JOIN group_members mem ON mem.chat_id = g.id AND mem.user_id = ?
                       WHERE gm.deleted = 0 AND gm.text LIKE ? ORDER BY gm.id DESC LIMIT 20""",
                    (uid, like)).fetchall()
                for r in grows:
                    nick = user_display(conn, r["user_id"])
                    if from_nick and from_nick.lower() not in (nick or "").lower():
                        continue
                    g = conn.execute("SELECT * FROM group_chats WHERE id = ?", (r["chat_id"],)).fetchone()
                    out["messages"].append(dict(chat_kind="group", chat_id=r["chat_id"],
                                                chat_title=group_title(conn, g), id=r["id"],
                                                text=(r["text"] or "")[:200], nick=nick,
                                                created_at=r["created_at"]))
                out["messages"].sort(key=lambda x: x["created_at"] or "", reverse=True)
                out["messages"] = out["messages"][:25]
            if wants("players") and q_clean:
                rows = conn.execute(
                    """SELECT * FROM listings WHERE hidden = 0 AND (nick LIKE ? OR about LIKE ?)
                       ORDER BY rating DESC LIMIT 15""", (like, like)).fetchall()
                for r in rows:
                    if game_id and not any(g["game_id"] == game_id for g in json.loads(r["games"] or "[]")):
                        continue
                    info = row_to_listing(r, uid, conn=conn)
                    out["players"].append(dict(listing_id=info["id"], nick=info["nick"], region=info["region_label"],
                                               rating=info["rating"], avatar=info["avatar"],
                                               games=[g["short"] for g in info["games"][:3]]))
            if wants("files") or wants("links"):
                # файлы и ссылки из тех чатов, где я участник
                grows = conn.execute(
                    """SELECT gm.*, g.id AS gid FROM group_messages gm
                       JOIN group_chats g ON g.id = gm.chat_id
                       JOIN group_members mem ON mem.chat_id = g.id AND mem.user_id = ?
                       WHERE gm.deleted = 0 ORDER BY gm.id DESC LIMIT 400""", (uid,)).fetchall()
                dms = conn.execute(
                    """SELECT m.* FROM messages m JOIN chats c ON c.id = m.chat_id
                       WHERE (c.user_id = ? OR c.peer_user_id = ?) AND m.deleted = 0
                       ORDER BY m.id DESC LIMIT 400""", (uid, uid)).fetchall()
                for r in list(grows) + list(dms):
                    gid = r["gid"] if "gid" in r.keys() else None
                    title = (group_title(conn, conn.execute("SELECT * FROM group_chats WHERE id = ?",
                                                            (gid,)).fetchone()) if gid else "Личный диалог")
                    meta = {}
                    if r["meta"]:
                        try:
                            meta = json.loads(r["meta"])
                        except Exception:
                            meta = {}
                    for att in (meta.get("attachments") or []):
                        item = dict(chat_kind=("group" if gid else "dm"), chat_id=(gid or r["chat_id"]),
                                    chat_title=title, id=r["id"], url=att.get("url", ""),
                                    name=att.get("name", ""), type=att.get("type", ""),
                                    created_at=r["created_at"], nick=user_display(conn, r["user_id"]) if gid
                                    else "")
                        if wants("files") and (not q_clean or q_clean.lower() in (item["name"] or "").lower()):
                            out["files"].append(item)
                    for u in re.findall(r"https?://[^\s]+", r["text"] or ""):
                        if wants("links") and (not q_clean or q_clean.lower() in u.lower()):
                            out["links"].append(dict(chat_kind=("group" if gid else "dm"),
                                                     chat_id=(gid or r["chat_id"]), chat_title=title,
                                                     id=r["id"], url=u[:300], created_at=r["created_at"]))
                out["files"] = out["files"][:25]
                out["links"] = out["links"][:25]
            # подсказки по играм каталога: искать можно и по названию игры
            games_hint = []
            if q_clean:
                low = q_clean.lower()
                games_hint = [dict(id=g["id"], name=g["name"]) for g in GAMES
                              if low in g["name"].lower() or low in g["short"].lower()][:5]
            return self._send(200, dict(query=q_clean, from_nick=from_nick, game=game_id,
                                        results=out, games=games_hint))

        # ==================== игровой слой чата (1.9) ====================
        if path == "/api/presence" and method == "GET":
            keys = [x for x in ((query.get("ids") or [""])[0].split(",")) if x][:50]
            out = {}
            for k in keys:
                uid_k = resolve_user_key(conn, k)
                out[k] = user_card(conn, uid_k) if uid_k else dict(
                    state="offline", label=PRESENCE_LABELS["offline"], nick=k, avatar="", game_name=None,
                    game_short=None, party_id=None, players=None, size=None, mode=None, looking=False,
                    listing_id=None, game_id=None)
            return self._send(200, dict(items=out))

        if path == "/api/inbox" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            touch_presence(conn, uid)
            conn.commit()
            blocked = blocked_ids(conn, uid)
            items = []
            # --- личные диалоги ---
            for c in conn.execute("SELECT * FROM chats WHERE user_id = ? OR peer_user_id = ? "
                                  "ORDER BY updated_at DESC", (uid, uid)).fetchall():
                peer_uid, peer_nick, is_initiator, my_unread = chat_partner(conn, c, uid)
                if peer_uid and peer_uid in blocked:
                    continue
                p = user_card(conn, peer_uid) if peer_uid else dict(state="offline", label="не в сети",
                                                                    avatar="", nick=peer_nick,
                                                                    game_name=None, party_id=None)
                last = conn.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                                    (c["id"],)).fetchone()
                last_text = ""
                if last:
                    last_text = "Сообщение удалено" if last["deleted"] else (last["text"] or "")
                typing_at = (c["typing_b"] if is_initiator else c["typing_a"]) if "typing_a" in c.keys() else None
                items.append(dict(
                    type="dm", id=c["id"], title=p["nick"] or peer_nick, avatar=p.get("avatar") or "",
                    presence=p.get("state"), presence_label=presence_line(p),
                    game_short=p.get("game_short") or "", game_id=p.get("game_id"),
                    unread=my_unread, muted=bool(c["muted_until"] and c["muted_until"] > now_iso()),
                    requested=bool(c["requested"]), requester_nick=(peer_nick if c["requested"] else ""),
                    typing=bool(typing_at and typing_at >= iso_cutoff(8 / 60)),
                    last_message=last_text, last_sender=(last["sender"] if last else None),
                    updated_at=c["updated_at"], members=0,
                ))
            # --- группы и пати ---
            for g in conn.execute(
                    """SELECT g.* FROM group_chats g JOIN group_members m ON m.chat_id = g.id
                       WHERE m.user_id = ? ORDER BY g.updated_at DESC""", (uid,)).fetchall():
                last = conn.execute("SELECT * FROM group_messages WHERE chat_id = ? AND deleted = 0 "
                                    "ORDER BY id DESC LIMIT 1", (g["id"],)).fetchone()
                last_text = ""
                if last:
                    last_text = (last["text"] or "")
                    if not last_text:
                        if last["kind"] == "poll":
                            try:
                                last_text = "Опрос: " + (json.loads(last["meta"] or "{}").get("question") or "")
                            except Exception:
                                last_text = "Опрос"
                        elif last["kind"] == "media":
                            try:
                                atts = json.loads(last["meta"] or "{}").get("attachments") or []
                                att = atts[0] if atts else {}
                                last_text = ("Скриншот: " if att.get("is_image") else
                                             "Клип: " if att.get("is_video") else "Файл: ") + str(att.get("name") or "")
                            except Exception:
                                last_text = "Файл"
                        elif last["kind"] == "invite":
                            last_text = "Приглашение в игру"
                        elif last["kind"] == "lfg":
                            last_text = "Поиск игроков"
                members = conn.execute("SELECT COUNT(*) AS c FROM group_members WHERE chat_id = ?",
                                       (g["id"],)).fetchone()["c"]
                muted = conn.execute("SELECT muted_until FROM group_members WHERE chat_id = ? AND user_id = ?",
                                     (g["id"], uid)).fetchone()
                typing_rows = conn.execute(
                    "SELECT user_id, ready FROM group_members WHERE chat_id = ? AND user_id != ?", (g["id"], uid)).fetchall()
                gg = GAME_BY_ID.get(g["game_id"]) if g["game_id"] else None
                items.append(dict(
                    type=("party" if g["kind"] == "party" else "group"), id=g["id"], title=group_title(conn, g),
                    avatar="", presence=None, presence_label=f"{members} участников",
                    game_short=(gg["short"] if gg else ""), game_id=g["game_id"],
                    unread=group_unread(conn, g["id"], uid),
                    muted=bool(muted and muted["muted_until"] and muted["muted_until"] > now_iso()),
                    requested=False, requester_nick="", typing=False,
                    last_message=last_text, last_sender=None,
                    updated_at=g["updated_at"], members=members, party_id=g["party_id"],
                ))
            items.sort(key=lambda x: x["updated_at"] or "", reverse=True)
            return self._send(200, dict(items=items, unread=dm_unread_total(conn, uid) + unread_groups_total(conn, uid)))

        # --- пати ---
        if path == "/api/parties" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            game = (query.get("game") or [""])[0]
            rows = conn.execute("SELECT * FROM parties WHERE status = 'open' ORDER BY id DESC LIMIT 50").fetchall()
            out = []
            for p in rows:
                pb = party_brief(conn, p["id"], uid)
                if not pb or (game and pb["game_id"] != game):
                    continue
                if conn.execute("SELECT 1 FROM blocks WHERE (user_id = ? AND blocked_user_id = ?) "
                                "OR (user_id = ? AND blocked_user_id = ?)",
                                (uid, p["leader_user_id"], p["leader_user_id"], uid)).fetchone():
                    continue
                out.append(pb)
            return self._send(200, dict(items=out))

        if path == "/api/parties" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            game_id = (body.get("game_id") or "")[:40]
            if game_id not in GAME_BY_ID:
                return self._send(400, {"error": "Выбери игру из каталога"})
            size = max(2, min(10, int(body.get("size") or 5)))
            mode = (body.get("mode") or "")[:20]
            open_now = conn.execute(
                "SELECT p.* FROM parties p JOIN group_members m ON m.chat_id = p.chat_id "
                "WHERE m.user_id = ? AND p.status IN ('open','playing')", (uid,)).fetchone()
            if open_now:
                pb = party_brief(conn, open_now["id"], uid)
                return self._send(200, dict(ok=True, already=True, party=pb))
            party_id, chat_id = create_party(conn, uid, game_id, mode=mode, region=(body.get("region") or "")[:20],
                                            rank=(body.get("rank") or "")[:20], mic=body.get("mic"),
                                            size=size, lang=(body.get("lang") or "")[:20],
                                            note=(body.get("note") or "")[:200])
            return self._send(200, dict(ok=True, party_id=party_id, chat_id=chat_id,
                                        party=party_brief(conn, party_id, uid)))

        m = re.match(r"^/api/parties/(\d+)$", path)
        if m and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            pb = party_brief(conn, int(m.group(1)), uid)
            if not pb:
                return self._send(404, {"error": "Пати не найдено"})
            return self._send(200, dict(party=pb))

        m = re.match(r"^/api/parties/(\d+)/(join|leave|ready|kick|transfer|start|close|invite)$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            party_id, action = int(m.group(1)), m.group(2)
            p = conn.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()
            if not p:
                return self._send(404, {"error": "Пати не найдено"})
            body = self._json_body()
            chat_id = p["chat_id"]
            is_member = in_group(conn, chat_id, uid)

            if action == "join":
                if is_member:
                    return self._send(200, dict(ok=True, already=True, chat_id=chat_id, party=party_brief(conn, party_id, uid)))
                if p["status"] != "open":
                    return self._send(400, {"error": "Пати уже играет или закрыто"})
                cnt = conn.execute("SELECT COUNT(*) AS c FROM group_members WHERE chat_id = ?",
                                   (chat_id,)).fetchone()["c"]
                if cnt >= p["size"]:
                    return self._send(400, {"error": "В пати уже нет мест"})
                if is_blocked_between(conn, uid, p["leader_user_id"]):
                    return self._send(403, {"error": "Недоступно"})
                conn.execute("INSERT INTO group_members (chat_id, user_id, joined_at, last_read_at) VALUES (?,?,?,?)",
                             (chat_id, uid, now_iso(), now_iso()))
                add_system_message(conn, chat_id, f"{user['nickname']} вступил в пати")
                conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.execute("UPDATE parties SET updated_at = ? WHERE id = ?", (now_iso(), party_id))
                conn.commit()
                for mid in group_member_ids(conn, chat_id):
                    if mid != uid:
                        push_async(mid, dict(title=f"В пати прибыл игрок · {pb_game_name(conn, p)}",
                                             body=f"{user['nickname']} присоединился", url="/?view=chats",
                                             tag=f"party-{party_id}"))
                return self._send(200, dict(ok=True, chat_id=chat_id, party=party_brief(conn, party_id, uid)))

            if not is_member and action != "close":
                return self._send(403, {"error": "Ты не в этом пати"})

            if action == "leave":
                conn.execute("DELETE FROM group_members WHERE chat_id = ? AND user_id = ?", (chat_id, uid))
                add_system_message(conn, chat_id, f"{user['nickname']} покинул пати")
                left = conn.execute("SELECT COUNT(*) AS c FROM group_members WHERE chat_id = ?",
                                    (chat_id,)).fetchone()["c"]
                if left and p["leader_user_id"] == uid:
                    new_leader = conn.execute("SELECT user_id FROM group_members WHERE chat_id = ? ORDER BY joined_at",
                                              (chat_id,)).fetchone()["user_id"]
                    conn.execute("UPDATE parties SET leader_user_id = ? WHERE id = ?", (new_leader, party_id))
                    conn.execute("UPDATE group_members SET role = 'member' WHERE chat_id = ?", (chat_id,))
                    conn.execute("UPDATE group_members SET role = 'leader' WHERE chat_id = ? AND user_id = ?",
                                 (chat_id, new_leader))
                    add_system_message(conn, chat_id, f"Лидер пати — {user_display(conn, new_leader)}")
                if not left:
                    conn.execute("UPDATE parties SET status = 'closed', closed_at = ? WHERE id = ?",
                                 (now_iso(), party_id))
                    close_session(conn, party_id)
                conn.commit()
                return self._send(200, dict(ok=True))

            if action == "ready":
                ready = 1 if body.get("ready", True) else 0
                conn.execute("UPDATE group_members SET ready = ? WHERE chat_id = ? AND user_id = ?",
                             (ready, chat_id, uid))
                conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.commit()
                return self._send(200, dict(ok=True, party=party_brief(conn, party_id, uid)))

            if action in ("kick", "transfer", "invite"):
                if p["leader_user_id"] != uid:
                    return self._send(403, {"error": "Это может только лидер пати"})
                target = (body.get("user_id") or "").strip()
                if not target and body.get("nick"):
                    r = conn.execute("SELECT id FROM users WHERE nickname = ? COLLATE NOCASE",
                                     (str(body["nick"]).strip(),)).fetchone()
                    target = r["id"] if r else ""
                if not target:
                    return self._send(400, {"error": "Игрок не найден"})
                target_nick = user_display(conn, target)
                if action == "kick":
                    conn.execute("DELETE FROM group_members WHERE chat_id = ? AND user_id = ?", (chat_id, target))
                    add_system_message(conn, chat_id, f"{target_nick} исключён из пати")
                elif action == "transfer":
                    conn.execute("UPDATE parties SET leader_user_id = ? WHERE id = ?", (target, party_id))
                    conn.execute("UPDATE group_members SET role = 'member' WHERE chat_id = ?", (chat_id,))
                    conn.execute("UPDATE group_members SET role = 'leader' WHERE chat_id = ? AND user_id = ?",
                                 (chat_id, target))
                    add_system_message(conn, chat_id, f"Лидер пати — {target_nick}")
                else:
                    already = in_group(conn, chat_id, target)
                    cnt = conn.execute("SELECT COUNT(*) AS c FROM group_members WHERE chat_id = ?",
                                       (chat_id,)).fetchone()["c"]
                    if already:
                        return self._send(200, dict(ok=True, already=True))
                    if cnt >= p["size"]:
                        return self._send(400, {"error": "В пати нет свободных мест"})
                    if is_blocked_between(conn, uid, target):
                        return self._send(403, {"error": "Недоступно"})
                    conn.execute("INSERT INTO group_members (chat_id, user_id, joined_at, last_read_at) VALUES (?,?,?,?)",
                                 (chat_id, target, now_iso(), now_iso()))
                    add_system_message(conn, chat_id, f"{user['nickname']} позвал {target_nick}")
                    push_async(target, dict(title="Тебя позвали в пати",
                                            body=f"{user['nickname']}: {pb_game_name(conn, p)}",
                                            url="/?view=chats", tag=f"party-{party_id}"))
                conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.commit()
                return self._send(200, dict(ok=True, party=party_brief(conn, party_id, uid)))

            if action == "start":
                if p["leader_user_id"] != uid and not in_group(conn, chat_id, uid):
                    return self._send(403, {"error": "Ты не в этом пати"})
                not_ready = [user_display(conn, r["user_id"]) for r in conn.execute(
                    "SELECT user_id FROM group_members WHERE chat_id = ? AND ready = 0 AND user_id != ?",
                    (chat_id, uid)).fetchall()]
                if not_ready and not body.get("force"):
                    return self._send(400, {"error": "Ждём готовности: " + ", ".join(not_ready), "waiting": not_ready})
                conn.execute("UPDATE parties SET status = 'playing', updated_at = ? WHERE id = ?", (now_iso(), party_id))
                members = [dict(user_id=r["user_id"], nick=user_display(conn, r["user_id"]))
                           for r in conn.execute("SELECT user_id FROM group_members WHERE chat_id = ?", (chat_id,))]
                conn.execute("INSERT INTO party_sessions (party_id, chat_id, game_id, leader_user_id, members, "
                             "started_at) VALUES (?,?,?,?,?,?)",
                             (party_id, chat_id, p["game_id"], p["leader_user_id"],
                              json.dumps(members, ensure_ascii=False), now_iso()))
                add_system_message(conn, chat_id, "Игра началась: " + pb_game_name(conn, p))
                conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.commit()
                for mid in group_member_ids(conn, chat_id):
                    if mid != uid:
                        push_async(mid, dict(title="Игра началась", body=pb_game_name(conn, p),
                                             url="/?view=chats", tag=f"party-{party_id}"))
                return self._send(200, dict(ok=True, party=party_brief(conn, party_id, uid)))

            if action == "close":
                conn.execute("UPDATE parties SET status = 'closed', closed_at = ? WHERE id = ?", (now_iso(), party_id))
                sess = close_session(conn, party_id)
                add_system_message(conn, chat_id, "Игровая сессия завершена"
                                    + (f" · {sess['minutes']} мин" if sess else ""))
                conn.commit()
                for mid in group_member_ids(conn, chat_id):
                    if mid != uid:
                        push_async(mid, dict(title="Сессия завершена",
                                             body=f"{pb_game_name(conn, p)} · можно позвать состав снова",
                                             url="/?view=chats", tag=f"party-{party_id}"))
                return self._send(200, dict(ok=True, session=sess))

        # --- групповые чаты и пати-чаты ---
        m = re.match(r"^/api/groups/(\d+)$", path)
        if m and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id = int(m.group(1))
            g = conn.execute("SELECT * FROM group_chats WHERE id = ?", (chat_id,)).fetchone()
            if not g or not in_group(conn, chat_id, uid):
                return self._send(404, {"error": "Чат не найден"})
            members = [user_card(conn, x) for x in group_member_ids(conn, chat_id)]
            return self._send(200, dict(chat=dict(id=chat_id, kind=g["kind"], title=group_title(conn, g),
                                                  game_id=g["game_id"], mode=g["mode"], region=g["region"],
                                                  rank=g["rank"], party_id=g["party_id"],
                                                  members=members),
                                        party=(party_brief(conn, g["party_id"], uid) if g["party_id"] else None)))

        m = re.match(r"^/api/groups/(\d+)/messages$", path)
        if m:
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id = int(m.group(1))
            g = conn.execute("SELECT * FROM group_chats WHERE id = ?", (chat_id,)).fetchone()
            if not g or not in_group(conn, chat_id, uid):
                return self._send(404, {"error": "Чат не найден"})
            if method == "GET":
                after = qint(query, "after", 0, lo=0)
                full = (query.get("all") or [""])[0] in ("1", "true")
                if full:
                    after = 0
                since = (query.get("since") or [""])[0] or now_iso(-10)
                if after <= 0:
                    rows = conn.execute("SELECT * FROM group_messages WHERE chat_id = ? ORDER BY id LIMIT 500",
                                        (chat_id,)).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM group_messages WHERE chat_id = ? AND id > ? ORDER BY id",
                                        (chat_id, after)).fetchall()
                changed_rows = []
                if after > 0:
                    changed_rows = conn.execute(
                        """SELECT * FROM group_messages WHERE chat_id = ? AND id <= ?
                           AND ((edited_at IS NOT NULL AND edited_at >= ?)
                                OR (deleted_at IS NOT NULL AND deleted_at >= ?)
                                OR (pinned = 1 AND created_at >= ?)) ORDER BY id LIMIT 100""",
                        (chat_id, after, since, since, since)).fetchall()
                ids = [r["id"] for r in list(rows) + list(changed_rows)]
                quotes = {}
                reply_ids = [r["reply_to"] for r in list(rows) + list(changed_rows) if r["reply_to"]]
                if reply_ids:
                    marks = ",".join("?" * len(reply_ids))
                    for q in conn.execute(f"SELECT * FROM group_messages WHERE id IN ({marks})", reply_ids):
                        quotes[q["id"]] = q
                reacts = {}
                if ids:
                    marks = ",".join("?" * len(ids))
                    for r in conn.execute(
                            f"SELECT message_id, value, COUNT(*) AS c, "
                            f"MAX(CASE WHEN user_id = ? THEN 1 ELSE 0 END) AS me FROM reactions "
                            f"WHERE chat_kind = 'group' AND chat_id = ? AND message_id IN ({marks}) "
                            f"GROUP BY message_id, value ORDER BY MIN(created_at)", [uid, chat_id] + ids):
                        reacts.setdefault(r["message_id"], []).append(
                            dict(value=r["value"], count=r["c"], mine=bool(r["me"])))
                members = []
                for mrow in conn.execute("SELECT * FROM group_members WHERE chat_id = ? AND user_id != ?",
                                         (chat_id, uid)):
                    mcard = user_card(conn, mrow["user_id"])
                    mcard["last_read_at"] = mrow["last_read_at"]
                    members.append(mcard)
                mrow = conn.execute("SELECT * FROM group_members WHERE chat_id = ? AND user_id = ?",
                                    (chat_id, uid)).fetchone()
                peer_read = conn.execute(
                    "SELECT MAX(last_read_at) AS m FROM group_members WHERE chat_id = ? AND user_id != ?",
                    (chat_id, uid)).fetchone()
                typing_rows = conn.execute(
                    "SELECT user_id, typing_at FROM group_members WHERE chat_id = ? AND user_id != ?",
                    (chat_id, uid)).fetchall()
                typing_names = [user_display(conn, r["user_id"]) for r in typing_rows
                                if r["typing_at"] and r["typing_at"] >= iso_cutoff(8 / 60)]
                return self._send(200, dict(
                    items=[group_item(conn, r, uid, quotes, reacts, "group", chat_id) for r in rows],
                    changed=[group_item(conn, r, uid, quotes, reacts, "group", chat_id) for r in changed_rows],
                    members=members,
                    peer_read_at=(peer_read["m"] if peer_read else None),
                    typing_names=typing_names,
                    party=(party_brief(conn, g["party_id"], uid) if g["party_id"] else None),
                ))
            if method == "POST":
                body = self._json_body()
                text = (body.get("text") or "").strip()[:4000]
                kind = (body.get("kind") or "text")[:12]
                meta = body.get("meta") or {}
                if kind not in ("text", "lfg", "invite", "poll", "media"):
                    return self._send(400, {"error": "Неизвестный тип сообщения"})
                if kind == "media" and not (meta.get("attachments") or []):
                    return self._send(400, {"error": "К сообщению не приложен файл"})
                if kind == "media":
                    clean = []
                    for att in (meta.get("attachments") or [])[:6]:
                        url = str(att.get("url") or "")
                        if not url.startswith("/uploads/"):
                            continue
                        clean.append(dict(url=url, name=str(att.get("name") or "файл")[:80],
                                          type=str(att.get("type") or "")[:60],
                                          size=int(att.get("size") or 0),
                                          is_image=bool(att.get("is_image")),
                                          is_video=bool(att.get("is_video"))))
                    if not clean:
                        return self._send(400, {"error": "Не удалось прочитать вложение"})
                    meta = dict(meta)
                    meta["attachments"] = clean
                if not text and kind == "text":
                    return self._send(400, {"error": "Пустое сообщение"})
                reply_to = body.get("reply_to")
                reply_to = int(reply_to) if str(reply_to or "").isdigit() else None
                edited = None
                mid = body.get("edit_id")
                if mid:
                    row = conn.execute("SELECT * FROM group_messages WHERE id = ? AND chat_id = ?",
                                       (int(mid), chat_id)).fetchone()
                    if not row:
                        return self._send(404, {"error": "Сообщение не найдено"})
                    if row["user_id"] != uid:
                        return self._send(403, {"error": "Можно править только свои сообщения"})
                    conn.execute("UPDATE group_messages SET text = ?, edited_at = ? WHERE id = ?",
                                 (text, now_iso(), int(mid)))
                    conn.commit()
                    return self._send(200, dict(ok=True, id=int(mid)))
                mentions = extract_mentions(conn, chat_id, text)
                if mentions:
                    meta = dict(meta or {})
                    meta["mentions"] = mentions
                cur = conn.execute(
                    "INSERT INTO group_messages (chat_id, user_id, text, kind, meta, reply_to, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (chat_id, uid, text, kind, json.dumps(meta, ensure_ascii=False), reply_to, now_iso()))
                mid = cur.lastrowid
                for mn in mentions:
                    if mn["user_id"] == uid:
                        continue
                    push_async(mn["user_id"], dict(
                        title=f"{user['nickname']} упомянул тебя · {group_title(conn, g)}",
                        body=(text or "")[:140], url="/?view=chats", tag=f"group-{chat_id}"))
                conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.execute("UPDATE group_members SET last_read_at = ? WHERE chat_id = ? AND user_id = ?",
                             (now_iso(), chat_id, uid))
                conn.commit()
                preview = text[:120] or ("Опрос" if kind == "poll" else "Приглашение" if kind == "invite"
                                         else "Поиск игроков" if kind == "lfg" else "Сообщение")
                for member in group_member_ids(conn, chat_id):
                    if member == uid:
                        continue
                    muted = conn.execute("SELECT muted_until FROM group_members WHERE chat_id = ? AND user_id = ?",
                                         (chat_id, member)).fetchone()
                    if muted and muted["muted_until"] and muted["muted_until"] > now_iso():
                        continue
                    push_async(member, dict(title=f"{user['nickname']} · {group_title(conn, g)}",
                                            body=preview, url="/?view=chats", tag=f"group-{chat_id}"))
                return self._send(200, dict(ok=True, id=mid))

        m = re.match(r"^/api/groups/(\d+)/(typing|read|mute|panels|members)$", path)
        if m:
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id, what = int(m.group(1)), m.group(2)
            if not in_group(conn, chat_id, uid):
                return self._send(404, {"error": "Чат не найден"})
            if what == "typing":
                conn.execute("UPDATE group_members SET typing_at = ? WHERE chat_id = ? AND user_id = ?",
                             (now_iso(), chat_id, uid))
                conn.commit()
                return self._send(200, dict(ok=True))
            if what == "read":
                conn.execute("UPDATE group_members SET last_read_at = ? WHERE chat_id = ? AND user_id = ?",
                             (now_iso(), chat_id, uid))
                conn.commit()
                return self._send(200, dict(ok=True))
            if what == "mute":
                body = self._json_body()
                minutes = int(body.get("minutes") or 0)
                until = None if minutes <= 0 else now_iso(minutes)
                conn.execute("UPDATE group_members SET muted_until = ? WHERE chat_id = ? AND user_id = ?",
                             (until, chat_id, uid))
                conn.commit()
                return self._send(200, dict(ok=True, muted=bool(until)))
            if what == "members":
                return self._send(200, dict(items=[user_card(conn, x) for x in group_member_ids(conn, chat_id)]))
            if what == "panels":
                rows = conn.execute("SELECT * FROM group_messages WHERE chat_id = ? AND deleted = 0 "
                                    "ORDER BY id DESC LIMIT 300", (chat_id,)).fetchall()
                pins, media, links, files = [], [], [], []
                for r in rows:
                    meta = {}
                    if r["meta"]:
                        try:
                            meta = json.loads(r["meta"])
                        except Exception:
                            meta = {}
                    if r["pinned"]:
                        pins.append(dict(id=r["id"], text=(r["text"] or "")[:200], nick=user_display(conn, r["user_id"]),
                                         created_at=r["created_at"]))
                    for u in re.findall(r"https?://[^\s]+", r["text"] or ""):
                        links.append(dict(id=r["id"], url=u[:300], nick=user_display(conn, r["user_id"]),
                                          created_at=r["created_at"]))
                    for att in (meta.get("attachments") or []):
                        item = dict(id=r["id"], url=att.get("url", ""), name=att.get("name", ""),
                                    type=att.get("type", ""), nick=user_display(conn, r["user_id"]),
                                    created_at=r["created_at"])
                        (media if str(att.get("type", "")).startswith("image") else files).append(item)
                return self._send(200, dict(pins=pins[:50], media=media[:60], links=links[:60], files=files[:60]))

        m = re.match(r"^/api/groups/(\d+)/messages/(\d+)/(edit|delete|react|pin|vote)$", path)
        if m:
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id, mid, action = int(m.group(1)), int(m.group(2)), m.group(3)
            if not in_group(conn, chat_id, uid):
                return self._send(404, {"error": "Чат не найден"})
            row = conn.execute("SELECT * FROM group_messages WHERE id = ? AND chat_id = ?", (mid, chat_id)).fetchone()
            if not row:
                return self._send(404, {"error": "Сообщение не найдено"})
            body = self._json_body()
            if action == "edit":
                if row["user_id"] != uid:
                    return self._send(403, {"error": "Можно править только свои сообщения"})
                text = (body.get("text") or "").strip()[:4000]
                if not text:
                    return self._send(400, {"error": "Пустое сообщение"})
                conn.execute("UPDATE group_messages SET text = ?, edited_at = ? WHERE id = ?", (text, now_iso(), mid))
                conn.commit()
                return self._send(200, dict(ok=True))
            if action == "delete":
                if row["user_id"] != uid:
                    return self._send(403, {"error": "Можно удалять только свои сообщения"})
                if row["deleted"]:
                    return self._send(400, {"error": "Сообщение уже удалено"})
                conn.execute("UPDATE group_messages SET deleted = 1, deleted_at = ?, text = '', reply_to = NULL "
                             "WHERE id = ?", (now_iso(), mid))
                conn.commit()
                return self._send(200, dict(ok=True))
            if action == "react":
                ok = toggle_reaction(conn, "group", chat_id, mid, uid, body.get("value"))
                if ok is None:
                    return self._send(400, {"error": "Такой реакции нет", "allowed": REACTIONS_ALLOWED})
                conn.commit()
                return self._send(200, dict(ok=True, added=ok, allowed=REACTIONS_ALLOWED))
            if action == "pin":
                new = 0 if row["pinned"] else 1
                conn.execute("UPDATE group_messages SET pinned = ? WHERE id = ?", (new, mid))
                conn.commit()
                return self._send(200, dict(ok=True, pinned=bool(new)))
            if action == "vote":
                if row["kind"] != "poll":
                    return self._send(400, {"error": "Это не опрос"})
                choice = int(body.get("choice", -1))
                meta = json.loads(row["meta"] or "{}")
                options = meta.get("options") or []
                if not (0 <= choice < len(options)):
                    return self._send(400, {"error": "Такого варианта нет"})
                if poll_expired(meta):
                    return self._send(400, {"error": "Опрос закрыт по времени"})
                multi = bool(meta.get("multi"))
                if multi:
                    # несколько вариантов: повторное нажатие снимает голос
                    had = conn.execute("SELECT 1 FROM poll_votes WHERE chat_kind = 'group' AND chat_id = ? "
                                       "AND message_id = ? AND user_id = ? AND choice = ?",
                                       (chat_id, mid, uid, choice)).fetchone()
                    if had:
                        conn.execute("DELETE FROM poll_votes WHERE chat_kind = 'group' AND chat_id = ? "
                                     "AND message_id = ? AND user_id = ? AND choice = ?",
                                     (chat_id, mid, uid, choice))
                        conn.commit()
                        return self._send(200, dict(ok=True, removed=True,
                                                    poll=poll_state(conn, "group", chat_id, mid, meta, uid)))
                else:
                    conn.execute("DELETE FROM poll_votes WHERE chat_kind = 'group' AND chat_id = ? AND message_id = ? "
                                 "AND user_id = ?", (chat_id, mid, uid))
                conn.execute("INSERT OR IGNORE INTO poll_votes (chat_kind, chat_id, message_id, user_id, choice, "
                             "created_at) VALUES ('group',?,?,?,?,?)", (chat_id, mid, uid, choice, now_iso()))
                conn.commit()
                return self._send(200, dict(ok=True, poll=poll_state(conn, "group", chat_id, mid, meta, uid)))

        # --- личные диалоги: запросы, реакции, закреплённые, опросы ---
        m = re.match(r"^/api/chats/(\d+)/(accept|ignore|mute)$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id, action = int(m.group(1)), m.group(2)
            c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                             (chat_id, uid, uid)).fetchone()
            if not c:
                return self._send(404, {"error": "Чат не найден"})
            if action == "accept":
                conn.execute("UPDATE chats SET requested = 0 WHERE id = ?", (chat_id,))
                conn.commit()
                return self._send(200, dict(ok=True))
            if action == "ignore":
                peer_uid, peer_nick, _, _ = chat_partner(conn, c, uid)
                conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
                conn.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
                conn.commit()
                return self._send(200, dict(ok=True, ignored=peer_nick))
            if action == "mute":
                minutes = int(self._json_body().get("minutes") or 0)
                until = None if minutes <= 0 else now_iso(minutes)
                conn.execute("UPDATE chats SET muted_until = ? WHERE id = ?", (until, chat_id))
                conn.commit()
                return self._send(200, dict(ok=True, muted=bool(until)))

        m = re.match(r"^/api/chats/(\d+)/messages/(\d+)/(react|pin|vote)$", path)
        if m:
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id, mid, action = int(m.group(1)), int(m.group(2)), m.group(3)
            c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                             (chat_id, uid, uid)).fetchone()
            if not c:
                return self._send(404, {"error": "Чат не найден"})
            row = conn.execute("SELECT * FROM messages WHERE id = ? AND chat_id = ?", (mid, chat_id)).fetchone()
            if not row:
                return self._send(404, {"error": "Сообщение не найдено"})
            body = self._json_body()
            if action == "react":
                ok = toggle_reaction(conn, "dm", chat_id, mid, uid, body.get("value"))
                if ok is None:
                    return self._send(400, {"error": "Такой реакции нет", "allowed": REACTIONS_ALLOWED})
                conn.commit()
                return self._send(200, dict(ok=True, added=ok, allowed=REACTIONS_ALLOWED))
            if action == "pin":
                new = 0 if (row["pinned"] if "pinned" in row.keys() else 0) else 1
                conn.execute("UPDATE messages SET pinned = ? WHERE id = ?", (new, mid))
                conn.commit()
                return self._send(200, dict(ok=True, pinned=bool(new)))
            return self._send(400, {"error": "Опросы доступны в групповых чатах"})

        # --- поиск игроков (LFG): карточка в чат + открытое пати ---
        if path == "/api/lfg" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            game_id = (body.get("game_id") or "")[:40]
            if game_id not in GAME_BY_ID:
                return self._send(400, {"error": "Выбери игру из каталога"})
            need = max(1, min(9, int(body.get("need") or 1)))
            size = max(2, min(10, int(body.get("size") or (need + 1))))
            # если у игрока уже есть открытое пати — карточка кладётся в него, второе не создаём
            open_now = conn.execute(
                "SELECT p.* FROM parties p JOIN group_members m ON m.chat_id = p.chat_id "
                "WHERE m.user_id = ? AND p.status IN ('open','playing') ORDER BY p.id DESC LIMIT 1",
                (uid,)).fetchone()
            if open_now:
                party_id, chat_id = open_now["id"], open_now["chat_id"]
                conn.execute(
                    "UPDATE parties SET game_id = ?, mode = ?, region = ?, rank = ?, mic = ?, lang = ?, "
                    "size = ?, note = ?, updated_at = ? WHERE id = ?",
                    (game_id, (body.get("mode") or "")[:20], (body.get("region") or "")[:20],
                     (body.get("rank") or "")[:20], int(bool(body.get("mic"))), (body.get("lang") or "")[:20],
                     size, (body.get("note") or "")[:200], now_iso(), party_id))
                gg0 = GAME_BY_ID.get(game_id)
                conn.execute("UPDATE group_chats SET game_id = ?, updated_at = ?, title = ? WHERE id = ?",
                             (game_id, now_iso(), "Пати · " + (gg0["name"] if gg0 else "Игра"), chat_id))
            else:
                party_id, chat_id = create_party(conn, uid, game_id,
                                                mode=(body.get("mode") or "")[:20],
                                                region=(body.get("region") or "")[:20],
                                                rank=(body.get("rank") or "")[:20],
                                                mic=body.get("mic"), size=size,
                                                lang=(body.get("lang") or "")[:20],
                                                note=(body.get("note") or "")[:200])
            g = GAME_BY_ID.get(game_id)
            meta = dict(party_id=party_id, game_id=game_id, game_name=(g["name"] if g else ""),
                        game_short=(g["short"] if g else ""), mode=(body.get("mode") or ""),
                        rank=(body.get("rank") or ""), region=(body.get("region") or ""),
                        need=need, mic=bool(body.get("mic")), lang=(body.get("lang") or ""),
                        note=(body.get("note") or "")[:200])
            # карточку кладём в пати-чат и, если просили, в личный диалог
            post_card(conn, chat_id, uid, "lfg", meta)
            target_chat = body.get("chat_id")
            target_kind = body.get("chat_kind") or "group"
            if target_chat:
                try:
                    target_chat = int(target_chat)
                except Exception:
                    target_chat = None
            if target_chat and target_kind == "group":
                # карточка уже лежит в этом чате (пати — это и есть групповой чат): второй раз не добавляем
                if target_chat != chat_id and in_group(conn, target_chat, uid):
                    post_card(conn, target_chat, uid, "lfg", meta)
                    conn.execute("UPDATE group_chats SET updated_at = ? WHERE id = ?", (now_iso(), target_chat))
            elif target_chat and target_kind == "dm":
                c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                                 (target_chat, uid, uid)).fetchone()
                if c:
                    _, peer_nick, is_initiator, _ = chat_partner(conn, c, uid)
                    mid = conn.execute(
                        "INSERT INTO messages (chat_id, sender, text, kind, meta, created_at) VALUES (?,?,?,?,?,?)",
                        (target_chat, "me" if is_initiator else "peer", "", "lfg",
                         json.dumps(meta, ensure_ascii=False), now_iso())).lastrowid
                    conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now_iso(), target_chat))
                    peer_uid = c["peer_user_id"] if is_initiator else c["user_id"]
                    if peer_uid:
                        push_async(peer_uid, dict(title="Ищут игроков: " + (g["name"] if g else ""),
                                                  body=f"{user['nickname']} собирает пати",
                                                  url="/?view=chats", tag=f"chat-{target_chat}"))
            conn.commit()
            return self._send(200, dict(ok=True, party_id=party_id, chat_id=chat_id, meta=meta))

        # --- приглашение в игру: отдельная карточка в личке ---
        m = re.match(r"^/api/chats/(\d+)/game-invite$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id = int(m.group(1))
            c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                             (chat_id, uid, uid)).fetchone()
            if not c:
                return self._send(404, {"error": "Чат не найден"})
            body = self._json_body()
            game_id = (body.get("game_id") or "")[:40]
            if game_id not in GAME_BY_ID:
                return self._send(400, {"error": "Выбери игру из каталога"})
            _, peer_nick, is_initiator, _ = chat_partner(conn, c, uid)
            peer_uid = c["peer_user_id"] if is_initiator else c["user_id"]
            if peer_uid and is_blocked_between(conn, uid, peer_uid):
                return self._send(403, {"error": "Недоступно"})
            g = GAME_BY_ID.get(game_id)
            meta = dict(game_id=game_id, game_name=(g["name"] if g else ""), game_short=(g["short"] if g else ""),
                        mode=(body.get("mode") or ""), rank=(body.get("rank") or ""),
                        region=(body.get("region") or ""), note=(body.get("note") or "")[:200],
                        state="pending", by=user["nickname"])
            mid = conn.execute(
                "INSERT INTO messages (chat_id, sender, text, kind, meta, created_at) VALUES (?,?,?,?,?,?)",
                (chat_id, "me" if is_initiator else "peer", "", "invite",
                 json.dumps(meta, ensure_ascii=False), now_iso())).lastrowid
            conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
            conn.commit()
            if peer_uid:
                push_async(peer_uid, dict(title="Приглашение в игру",
                                          body=f"{user['nickname']}: {g['name'] if g else ''}",
                                          url="/?view=chats", tag=f"chat-{chat_id}"))
            return self._send(200, dict(ok=True, id=mid))

        m = re.match(r"^/api/chats/(\d+)/messages/(\d+)/invite-(accept|decline)$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            chat_id, mid, what = int(m.group(1)), int(m.group(2)), m.group(3)
            c = conn.execute("SELECT * FROM chats WHERE id = ? AND (user_id = ? OR peer_user_id = ?)",
                             (chat_id, uid, uid)).fetchone()
            if not c:
                return self._send(404, {"error": "Чат не найден"})
            row = conn.execute("SELECT * FROM messages WHERE id = ? AND chat_id = ?", (mid, chat_id)).fetchone()
            if not row or row["kind"] != "invite":
                return self._send(404, {"error": "Приглашение не найдено"})
            meta = json.loads(row["meta"] or "{}")
            if meta.get("state") != "pending":
                return self._send(400, {"error": "Уже отвечено"})
            _, peer_nick, is_initiator, _ = chat_partner(conn, c, uid)
            peer_uid = c["peer_user_id"] if is_initiator else c["user_id"]
            if what == "accept":
                meta["state"] = "accepted"
                meta["answered_by"] = user["nickname"]
                conn.execute("UPDATE messages SET meta = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), mid))
                conn.execute("INSERT INTO messages (chat_id, sender, text, kind, created_at) VALUES (?,?,?,?,?)",
                             (chat_id, "me" if not is_initiator else "peer",
                              f"{user['nickname']} принял приглашение: {meta.get('game_name', '')}", "system", now_iso()))
                if peer_uid:
                    push_async(peer_uid, dict(title="Приглашение принято",
                                              body=f"{user['nickname']} готов играть: {meta.get('game_name','')}",
                                              url="/?view=chats", tag=f"chat-{chat_id}"))
                conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (now_iso(), chat_id))
                conn.commit()
                return self._send(200, dict(ok=True, chat_id=chat_id))
            meta["state"] = "declined"
            meta["answered_by"] = user["nickname"]
            conn.execute("UPDATE messages SET meta = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), mid))
            conn.commit()
            return self._send(200, dict(ok=True))

        # --- тиммейты: «играли вместе» и добавление в свой список ---
        if path == "/api/teammates" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            items = []
            rows = conn.execute("SELECT * FROM teammates WHERE user_id = ? ORDER BY id DESC LIMIT 200",
                                (uid,)).fetchall()
            played = conn.execute("SELECT * FROM party_sessions ORDER BY id DESC LIMIT 200").fetchall()
            for r in rows:
                mate = r["mate_user_id"]
                if not mate or is_blocked_between(conn, uid, mate):
                    continue
                back = conn.execute("SELECT 1 FROM teammates WHERE user_id = ? AND mate_user_id = ?",
                                    (mate, uid)).fetchone()
                shared = 0
                last_game = None
                for ps in played:
                    mem = json.loads(ps["members"] or "[]")
                    ids = [m.get("user_id") for m in mem]
                    if uid in ids and mate in ids:
                        shared += 1
                        if not last_game:
                            last_game = ps["game_id"]
                g = GAME_BY_ID.get(last_game) if last_game else None
                p = user_presence(conn, mate)
                items.append(dict(
                    nick=p.get("nick") or user_display(conn, mate), user_key=mate[:8],
                    avatar=p.get("avatar") or "", mutual=bool(back), added_at=r["created_at"],
                    sessions_together=shared, online=(p.get("state") != "offline"),
                    status=p.get("label") or "",
                    game_name=(g["name"] if g else ""), game_short=(g["short"] if g else "")))
            return self._send(200, dict(items=items))

        if path == "/api/teammates" and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            body = self._json_body()
            nick = (body.get("nick") or "").strip()[:64]
            mate = resolve_user_key(conn, nick)
            if not mate:
                return self._send(404, {"error": "Игрок не найден или у него нет аккаунта"})
            if mate == uid:
                return self._send(400, {"error": "Это ты"})
            if is_blocked_between(conn, uid, mate):
                return self._send(403, {"error": "Недоступно"})
            conn.execute("INSERT OR IGNORE INTO teammates (user_id, mate_user_id, note, created_at) "
                         "VALUES (?,?,?,?)", (uid, mate, (body.get("note") or "")[:200], now_iso()))
            conn.commit()
            back = conn.execute("SELECT 1 FROM teammates WHERE user_id = ? AND mate_user_id = ?",
                                (mate, uid)).fetchone()
            push_async(mate, dict(title="Ты в списке тиммейтов",
                                  body=f"{user['nickname']} добавил тебя в тиммейты",
                                  url="/?view=chats", tag=f"mate-{uid}"))
            total = conn.execute("SELECT COUNT(*) c FROM teammates WHERE user_id = ?", (uid,)).fetchone()["c"]
            return self._send(200, dict(ok=True, mutual=bool(back),
                                        nick=user_display(conn, mate), mates_total=total))

        m = re.match(r"^/api/teammates/(.+)$", path)
        if m and method == "DELETE":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            mate = resolve_user_key(conn, unquote(m.group(1)))
            if mate:
                conn.execute("DELETE FROM teammates WHERE user_id = ? AND mate_user_id = ?", (uid, mate))
                conn.commit()
            return self._send(200, dict(ok=True))

        # --- история сессий и «играть снова» ---
        if path == "/api/sessions" and method == "GET":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            out = []
            for r in conn.execute("SELECT * FROM party_sessions ORDER BY id DESC LIMIT 100").fetchall():
                members = json.loads(r["members"] or "[]")
                if not any(m.get("user_id") == uid for m in members):
                    continue
                started = r["started_at"] or now_iso()
                ended = r["ended_at"]
                minutes = r["minutes"]
                if minutes is None:
                    try:
                        t0 = datetime.fromisoformat(started)
                        t1 = datetime.fromisoformat(ended) if ended else datetime.now(timezone.utc)
                        minutes = max(1, int((t1 - t0).total_seconds() // 60))
                    except Exception:
                        minutes = 0
                g = GAME_BY_ID.get(r["game_id"])
                out.append(dict(id=r["id"], game_id=r["game_id"], game_name=(g["name"] if g else ""),
                                game_short=(g["short"] if g else ""), chat_id=r["chat_id"],
                                minutes=minutes, started_at=started, ended_at=ended,
                                finished=bool(ended), players=len(members),
                                members=[dict(user_id=m.get("user_id"), nick=m.get("nick"),
                                              is_me=(m.get("user_id") == uid),
                                              is_teammate=bool(m.get("user_id") and conn.execute(
                                                  "SELECT 1 FROM teammates WHERE user_id = ? AND mate_user_id = ?",
                                                  (uid, m.get("user_id"))).fetchone()),
                                              can_add=bool(m.get("user_id") and m.get("user_id") != uid and not conn.execute(
                                                  "SELECT 1 FROM teammates WHERE user_id = ? AND mate_user_id = ?",
                                                  (uid, m.get("user_id"))).fetchone() and not is_blocked_between(
                                                  conn, uid, m.get("user_id"))))
                                              for m in members]))
            return self._send(200, dict(items=out[:30]))

        m = re.match(r"^/api/sessions/(\d+)/play-again$", path)
        if m and method == "POST":
            if not user:
                return self._send(401, {"error": "Нужен вход"})
            r = conn.execute("SELECT * FROM party_sessions WHERE id = ?", (int(m.group(1)),)).fetchone()
            if not r:
                return self._send(404, {"error": "Сессия не найдена"})
            members = json.loads(r["members"] or "[]")
            if not any(x.get("user_id") == uid for x in members):
                return self._send(403, {"error": "Ты не участвовал в этой сессии"})
            open_now = conn.execute(
                "SELECT p.* FROM parties p JOIN group_members gm ON gm.chat_id = p.chat_id "
                "WHERE gm.user_id = ? AND p.status IN ('open','playing')", (uid,)).fetchone()
            if open_now:
                pb = party_brief(conn, open_now["id"], uid)
                return self._send(200, dict(ok=True, already=True, party=pb, chat_id=open_now["chat_id"]))
            party_id, chat_id = create_party(conn, uid, r["game_id"], size=max(2, len(members)))
            invited = []
            for x in members:
                mid_uid = x.get("user_id")
                if not mid_uid or mid_uid == uid:
                    continue
                if is_blocked_between(conn, uid, mid_uid):
                    continue
                conn.execute("INSERT OR IGNORE INTO group_members (chat_id, user_id, joined_at) VALUES (?,?,?)",
                             (chat_id, mid_uid, now_iso()))
                invited.append(user_display(conn, mid_uid))
                push_async(mid_uid, dict(title="Состав снова в сборе",
                                         body=f"{user['nickname']} собирает пати: "
                                              f"{GAME_BY_ID.get(r['game_id'], {}).get('name', '')}",
                                         url="/?view=chats", tag=f"party-{party_id}"))
            if invited:
                add_system_message(conn, chat_id, "Приглашены те, с кем играли: " + ", ".join(invited))
            conn.commit()
            return self._send(200, dict(ok=True, party=party_brief(conn, party_id, uid), chat_id=chat_id))

        return self._send(404, {"error": "Неизвестный метод API"})

    # --- вспомогательное ---
    def apply_filters(self, items, query):
        q = (query.get("q") or [""])[0].strip().lower()
        game = (query.get("game") or [""])[0]
        mode = (query.get("mode") or [""])[0]
        platform = (query.get("platform") or [""])[0]
        region = (query.get("region") or [""])[0]
        lang = (query.get("lang") or [""])[0]
        skill = qint(query, "skill", 0, lo=0, hi=5)
        vibe = (query.get("vibe") or [""])[0]
        mic = (query.get("mic") or [""])[0] == "1"
        online = (query.get("online") or [""])[0] == "1"

        out = []
        for i in items:
            if q and q not in i["nick"].lower() and q not in (i["about"] or "").lower():
                continue
            if game and not any(g["game_id"] == game for g in i["games"]):
                continue
            if mode and not any(mode in g["modes"] for g in i["games"]):
                continue
            if platform and platform not in i["platforms"]:
                continue
            if region and i["region"] != region:
                continue
            if lang and lang not in i["languages"]:
                continue
            if skill and i["skill"] < skill:
                continue
            if vibe and i["vibe"] != vibe:
                continue
            if mic and not i["mic"]:
                continue
            if online and not i["online"]:
                continue
            out.append(i)
        return out

    def seed_welcome_chats(self, conn, uid):
        if not DEMO_DATA:
            return  # с реальными игроками никаких выдуманных диалогов
        """При первом входе создаём пару живых диалогов, чтобы чат не был пустым."""
        rnd = random.Random(uid)
        rows = conn.execute("SELECT * FROM listings WHERE is_seed = 1 ORDER BY RANDOM() LIMIT 2").fetchall()
        seeds = [
            ("Привет! Увидел твою анкету — ищу пати на вечер, сыграем?", "Конечно! Я онлайн после 19:00, стучись"),
            ("Йо, ты тоже ищешь состав? Может, объединимся?", "Да, отличная идея. Давай начнём с пары каток, посмотрим на синергию."),
        ]
        for idx, row in enumerate(rows):
            greeting, answer = seeds[idx % len(seeds)]
            cur = conn.execute(
                "INSERT INTO chats (user_id, listing_id, peer_nick, unread, created_at, updated_at) VALUES (?,?,?,1,?,?)",
                (uid, row["id"], row["nick"], now_iso(-6), now_iso(-5)))
            chat_id = cur.lastrowid
            conn.execute("INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?,?,?,?)",
                         (chat_id, "me", greeting, now_iso(-6)))
            conn.execute("INSERT INTO messages (chat_id, sender, text, created_at) VALUES (?,?,?,?)",
                         (chat_id, "peer", answer, now_iso(-5)))
        conn.commit()


def main():
    init_db()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"SQUADUP запущен: http://0.0.0.0:{PORT} | Discord OAuth: {'включён' if DISCORD_ENABLED else 'выключен'} | база: {DB_PATH}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
