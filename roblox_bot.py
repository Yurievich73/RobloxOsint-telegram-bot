import time
import json
import os
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime

# Кеш ников и аватарок
username_cache = {}
avatar_cache = {}

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
ADMIN_ID = 123456789  # Замени на свой Telegram ID
FREE_LIMIT = 3        # Бесплатно — 3 игрока
CHECK_INTERVAL = 45
DATA_FILE = "users.json"

bot = telebot.TeleBot(BOT_TOKEN)

STATUS_NAMES = {
    0: "Офлайн 💤",
    1: "В сети 🌐",
    2: "В игре 🎮",
    3: "В Roblox Studio 🛠️"
}

user_states = {}
waiting_for_id = set()


# ===================== РАБОТА С ФАЙЛОМ =====================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_user(chat_id):
    data = load_data()
    uid = str(chat_id)
    if uid not in data:
        data[uid] = {"players": [], "premium": False, "history": {}}
        save_data(data)
    # Миграция старого формата
    if isinstance(data[uid], list):
        data[uid] = {"players": data[uid], "premium": False, "history": {}}
        save_data(data)
    return data, uid

def is_premium(chat_id):
    data, uid = get_user(chat_id)
    if str(chat_id) == str(ADMIN_ID):
        return True
    return data[uid].get("premium", False)


# ===================== ROBLOX API =====================

def get_roblox_presence(user_ids):
    url = "https://presence.roblox.com/v1/presence/users"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        response = requests.post(url, json={"userIds": user_ids}, headers=headers, timeout=10)
        if response.status_code == 403:
            csrf = response.headers.get("x-csrf-token")
            if csrf:
                headers["X-CSRF-TOKEN"] = csrf
                response = requests.post(url, json={"userIds": user_ids}, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("userPresences", [])
    except Exception as e:
        print(f"❌ Ошибка сети: {e}")
    return []

def get_roblox_username(user_id):
    if user_id in username_cache:
        return username_cache[user_id]
    try:
        r = requests.get(f"https://users.roblox.com/v1/users/{user_id}", timeout=10)
        if r.status_code == 200:
            name = r.json().get("name", str(user_id))
            username_cache[user_id] = name
            return name
    except:
        pass
    return str(user_id)

def get_roblox_avatar(user_id):
    if user_id in avatar_cache:
        return avatar_cache[user_id]
    try:
        r = requests.get(
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png",
            timeout=10
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                url = data[0].get("imageUrl")
                avatar_cache[user_id] = url
                return url
    except:
        pass
    return None

def get_game_name(place_id):
    if not place_id:
        return None
    try:
        r = requests.get(f"https://games.roblox.com/v1/games?universeIds={place_id}", timeout=10)
        if r.status_code == 200:
            games = r.json().get("data", [])
            if games:
                return games[0].get("name")
    except:
        pass
    return None


# ===================== КНОПКИ =====================

def main_menu(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Добавить игрока", callback_data="add"))
    markup.add(InlineKeyboardButton("📋 Мой список", callback_data="list"))
    markup.add(InlineKeyboardButton("📊 История", callback_data="history"))
    if not is_premium(chat_id):
        markup.add(InlineKeyboardButton("⭐ Получить Премиум", callback_data="premium_info"))
    if str(chat_id) == str(ADMIN_ID):
        markup.add(InlineKeyboardButton("👑 Админ панель", callback_data="admin"))
    return markup


# ===================== КОМАНДЫ =====================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    get_user(chat_id)
    premium = is_premium(chat_id)
    plan = "⭐ Премиум" if premium else f"🆓 Бесплатный (до {FREE_LIMIT} игроков)"

    bot.send_message(
        chat_id,
        f"👋 Привет, *{message.from_user.first_name}*!\n\n"
        f"Я слежу за игроками в Roblox и уведомляю тебя в реальном времени.\n\n"
        f"📌 Твой план: {plan}\n\n"
        f"Выбери действие:",
        parse_mode="Markdown",
        reply_markup=main_menu(chat_id)
    )


# ===================== КОЛБЭКИ =====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    uid = str(chat_id)
    data, _ = get_user(chat_id)

    # Добавить игрока
    if call.data == "add":
        players = data[uid]["players"]
        premium = is_premium(chat_id)
        if not premium and len(players) >= FREE_LIMIT:
            bot.answer_callback_query(call.id, "⚠️ Лимит достигнут!", show_alert=True)
            bot.send_message(chat_id,
                f"⚠️ В бесплатном плане максимум {FREE_LIMIT} игрока.\n\n"
                f"Купи ⭐ Премиум для безлимитного отслеживания!",
                reply_markup=main_menu(chat_id))
            return
        waiting_for_id.add(uid)
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "🔍 Пришли мне *Roblox ID* игрока (только цифры):", parse_mode="Markdown")

    # Список игроков
    elif call.data == "list":
        players = data[uid]["players"]
        bot.answer_callback_query(call.id)
        if not players:
            bot.send_message(chat_id, "📋 Твой список пуст. Добавь игроков!", reply_markup=main_menu(chat_id))
            return

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➕ Добавить ещё", callback_data="add"))
        text = "📋 *Твои игроки:*\n\n"
        for pid in players:
            username = get_roblox_username(pid)
            text += f"• *{username}* (`{pid}`)\n"
            markup.add(InlineKeyboardButton(f"❌ Удалить {username}", callback_data=f"del_{pid}"))
        markup.add(InlineKeyboardButton("🔙 Назад", callback_data="back"))
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

    # История
    elif call.data == "history":
        bot.answer_callback_query(call.id)
        history = data[uid].get("history", {})
        if not history:
            bot.send_message(chat_id, "📊 История пока пуста.", reply_markup=main_menu(chat_id))
            return

        text = "📊 *История активности:*\n\n"
        for roblox_id, events in history.items():
            username = get_roblox_username(int(roblox_id))
            text += f"👤 *{username}*\n"
            for event in events[-5:]:  # Последние 5 событий
                text += f"  {event}\n"
            text += "\n"

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔙 Назад", callback_data="back"))
        bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

    # Инфо о премиуме
    elif call.data == "premium_info":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id,
            "⭐ *Премиум план*\n\n"
            "✅ Безлимитное количество игроков\n"
            "✅ История активности\n"
            "✅ Приоритетные уведомления\n\n"
            "Для покупки напишите администратору.",
            parse_mode="Markdown",
            reply_markup=main_menu(chat_id))

    # Админ панель
    elif call.data == "admin":
        if str(chat_id) != str(ADMIN_ID):
            bot.answer_callback_query(call.id, "❌ Нет доступа")
            return
        bot.answer_callback_query(call.id)
        data_all = load_data()
        total_users = len(data_all)
        premium_users = sum(1 for u in data_all.values() if isinstance(u, dict) and u.get("premium"))
        total_players = sum(len(u["players"]) for u in data_all.values() if isinstance(u, dict))

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➕ Выдать премиум", callback_data="give_premium"))
        markup.add(InlineKeyboardButton("➖ Забрать премиум", callback_data="remove_premium"))
        markup.add(InlineKeyboardButton("🔙 Назад", callback_data="back"))

        bot.send_message(chat_id,
            f"👑 *Админ панель*\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"⭐ Премиум пользователей: {premium_users}\n"
            f"🎮 Всего отслеживается игроков: {total_players}",
            parse_mode="Markdown",
            reply_markup=markup)

    elif call.data == "give_premium":
        if str(chat_id) != str(ADMIN_ID):
            return
        waiting_for_id.add(f"give_premium_{uid}")
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "Пришли Telegram ID пользователя которому выдать премиум:")

    elif call.data == "remove_premium":
        if str(chat_id) != str(ADMIN_ID):
            return
        waiting_for_id.add(f"remove_premium_{uid}")
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "Пришли Telegram ID пользователя у которого забрать премиум:")

    # Удалить игрока
    elif call.data.startswith("del_"):
        roblox_id = int(call.data.split("_")[1])
        if roblox_id in data[uid]["players"]:
            data[uid]["players"].remove(roblox_id)
            save_data(data)
            if uid in user_states and roblox_id in user_states[uid]:
                del user_states[uid][roblox_id]
            bot.answer_callback_query(call.id, "✅ Удалено!")
            bot.send_message(chat_id, f"❌ Игрок удалён.", reply_markup=main_menu(chat_id))
        else:
            bot.answer_callback_query(call.id, "Не найдено")

    # Назад
    elif call.data == "back":
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=main_menu(chat_id))


# ===================== ВВОД ТЕКСТА =====================

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    uid = str(chat_id)
    text = message.text.strip()

    # Выдача премиума (админ)
    if f"give_premium_{uid}" in waiting_for_id:
        waiting_for_id.discard(f"give_premium_{uid}")
        if text.isdigit():
            target = text
            data = load_data()
            if target not in data:
                data[target] = {"players": [], "premium": False, "history": {}}
            data[target]["premium"] = True
            save_data(data)
            bot.send_message(chat_id, f"✅ Премиум выдан пользователю {target}", reply_markup=main_menu(chat_id))
            try:
                bot.send_message(int(target), "🎉 Вам выдан ⭐ Премиум план! Теперь вы можете отслеживать неограниченное количество игроков.")
            except:
                pass
        else:
            bot.send_message(chat_id, "❌ Неверный ID", reply_markup=main_menu(chat_id))
        return

    # Забрать премиум (админ)
    if f"remove_premium_{uid}" in waiting_for_id:
        waiting_for_id.discard(f"remove_premium_{uid}")
        if text.isdigit():
            target = text
            data = load_data()
            if target in data:
                data[target]["premium"] = False
                save_data(data)
            bot.send_message(chat_id, f"✅ Премиум убран у пользователя {target}", reply_markup=main_menu(chat_id))
        else:
            bot.send_message(chat_id, "❌ Неверный ID", reply_markup=main_menu(chat_id))
        return

    # Добавление игрока
    if uid in waiting_for_id:
        if not text.isdigit():
            bot.send_message(chat_id, "⚠️ ID должен содержать только цифры! Попробуй ещё раз:")
            return

        roblox_id = int(text)
        data, _ = get_user(chat_id)

        if roblox_id in data[uid]["players"]:
            bot.send_message(chat_id, "⚠️ Этот игрок уже есть в списке!", reply_markup=main_menu(chat_id))
            waiting_for_id.discard(uid)
            return

        username = get_roblox_username(roblox_id)
        if username == str(roblox_id):
            bot.send_message(chat_id, "❌ Игрок с таким ID не найден. Проверь ID и попробуй ещё раз:")
            return

        data[uid]["players"].append(roblox_id)
        save_data(data)
        waiting_for_id.discard(uid)

        avatar_url = get_roblox_avatar(roblox_id)
        caption = (f"✅ Игрок *{username}* добавлен!\n"
                   f"Буду присылать уведомления об изменении его статуса.")

        if avatar_url:
            bot.send_photo(chat_id, avatar_url, caption=caption, parse_mode="Markdown", reply_markup=main_menu(chat_id))
        else:
            bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=main_menu(chat_id))
        return

    bot.send_message(chat_id, "Используй кнопки 👇", reply_markup=main_menu(chat_id))


# ===================== МОНИТОРИНГ =====================

def add_history(data, uid, roblox_id, event_text):
    if "history" not in data[uid]:
        data[uid]["history"] = {}
    rid = str(roblox_id)
    if rid not in data[uid]["history"]:
        data[uid]["history"][rid] = []
    now = datetime.now().strftime("%d.%m %H:%M")
    data[uid]["history"][rid].append(f"[{now}] {event_text}")
    # Храним последние 50 событий
    data[uid]["history"][rid] = data[uid]["history"][rid][-50:]

def monitor_loop():
    print("🔄 Мониторинг запущен...")
    while True:
        try:
            data = load_data()

            all_ids = set()
            for user in data.values():
                if isinstance(user, dict):
                    all_ids.update(user.get("players", []))

            if all_ids:
                presences = get_roblox_presence(list(all_ids))
                presence_map = {p["userId"]: p for p in presences}

                for uid, user_data in data.items():
                    if not isinstance(user_data, dict):
                        continue
                    player_ids = user_data.get("players", [])

                    if uid not in user_states:
                        user_states[uid] = {}

                    for roblox_id in player_ids:
                        presence = presence_map.get(roblox_id)
                        if not presence:
                            continue

                        current_status = presence.get("userPresenceType", 0)
                        current_place = presence.get("lastLocation", "")
                        place_id = presence.get("placeId")
                        last_status = user_states[uid].get(roblox_id)

                        if last_status is None:
                            user_states[uid][roblox_id] = current_status
                            continue

                        if current_status == last_status:
                            continue

                        username = get_roblox_username(roblox_id)
                        avatar_url = get_roblox_avatar(roblox_id)

                        if current_status == 2:
                            game_name = get_game_name(place_id) or current_place or "неизвестная игра"
                            msg = f"🚨 *{username}* зашёл в игру!\n🎮 {game_name}"
                            history_text = f"Зашёл в игру: {game_name}"
                        elif current_status == 1:
                            msg = f"🌐 *{username}* зашёл в сеть."
                            history_text = "Зашёл в сеть"
                        elif current_status == 3:
                            msg = f"🛠️ *{username}* открыл Roblox Studio."
                            history_text = "Открыл Roblox Studio"
                        elif current_status == 0:
                            msg = f"💤 *{username}* вышел офлайн."
                            history_text = "Вышел офлайн"
                        else:
                            msg = f"🔄 *{username}*: {STATUS_NAMES.get(current_status, 'Неизвестно')}"
                            history_text = f"Статус: {STATUS_NAMES.get(current_status, '?')}"

                        # Сохраняем в историю
                        add_history(data, uid, roblox_id, history_text)

                        try:
                            if avatar_url:
                                bot.send_photo(int(uid), avatar_url, caption=msg, parse_mode="Markdown")
                            else:
                                bot.send_message(int(uid), msg, parse_mode="Markdown")
                        except Exception as e:
                            print(f"❌ Не смог отправить в {uid}: {e}")

                        user_states[uid][roblox_id] = current_status

                save_data(data)

        except Exception as e:
            print(f"❌ Ошибка в мониторинге: {e}")

        time.sleep(CHECK_INTERVAL)


# ===================== ЗАПУСК =====================

if __name__ == "__main__":
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    print("🤖 Бот запущен!")
    bot.infinity_polling()
