import time
import json
import os
import threading
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Кеш ников — чтобы не делать лишние запросы к Roblox API
username_cache = {}

# --- НАСТРОЙКИ ---
BOT_TOKEN = "8856024899:AAH7aRc-_01lKNBsOjYdjH4yTcn94vovu88"
CHECK_INTERVAL = 1
DATA_FILE = "users.json"

bot = telebot.TeleBot(BOT_TOKEN)

STATUS_NAMES = {
    0: "Офлайн 💤",
    1: "На сайте/в приложении 🌐",
    2: "В игре 🎮",
    3: "В Roblox Studio 🛠️"
}

# Статусы игроков в памяти: { chat_id: { roblox_id: last_status } }
user_states = {}

# Пользователи которые сейчас вводят Roblox ID
waiting_for_id = set()


# ===================== РАБОТА С ФАЙЛОМ =====================

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ===================== ROBLOX API =====================

def get_roblox_presence(user_ids):
    """Получить статусы сразу нескольких игроков"""
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
    """Получить никнейм по Roblox ID (с кешем)"""
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


# ===================== КНОПКИ =====================

def main_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Добавить игрока", callback_data="add"))
    markup.add(InlineKeyboardButton("📋 Мой список", callback_data="list"))
    return markup


# ===================== КОМАНДЫ =====================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = str(message.chat.id)
    data = load_data()
    if chat_id not in data:
        data[chat_id] = []
        save_data(data)

    bot.send_message(
        message.chat.id,
        "👋 Привет! Я слежу за игроками в Roblox и уведомляю тебя когда они заходят в игру или выходят.\n\nВыбери действие:",
        reply_markup=main_menu()
    )


# ===================== КНОПКИ (колбэки) =====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = str(call.message.chat.id)

    if call.data == "add":
        waiting_for_id.add(chat_id)
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, "🔍 Пришли мне *Roblox ID* игрока (только цифры):", parse_mode="Markdown")

    elif call.data == "list":
        data = load_data()
        players = data.get(chat_id, [])
        bot.answer_callback_query(call.id)

        if not players:
            bot.send_message(call.message.chat.id, "📋 Твой список пуст. Добавь игроков!", reply_markup=main_menu())
            return

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➕ Добавить ещё", callback_data="add"))
        text = "📋 *Твои игроки:*\n"
        for pid in players:
            username = get_roblox_username(pid)
            text += f"• {username} (`{pid}`)\n"
            markup.add(InlineKeyboardButton(f"❌ Удалить {username}", callback_data=f"del_{pid}"))

        bot.send_message(call.message.chat.id, text, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("del_"):
        roblox_id = int(call.data.split("_")[1])
        data = load_data()
        if chat_id in data and roblox_id in data[chat_id]:
            data[chat_id].remove(roblox_id)
            save_data(data)
            if chat_id in user_states and roblox_id in user_states[chat_id]:
                del user_states[chat_id][roblox_id]
            bot.answer_callback_query(call.id, "✅ Удалено!")
            bot.send_message(call.message.chat.id, f"❌ Игрок `{roblox_id}` удалён.", parse_mode="Markdown", reply_markup=main_menu())
        else:
            bot.answer_callback_query(call.id, "Не найдено")


# ===================== ВВОД ROBLOX ID =====================

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = str(message.chat.id)

    if chat_id not in waiting_for_id:
        bot.send_message(message.chat.id, "Используй кнопки 👇", reply_markup=main_menu())
        return

    text = message.text.strip()

    if not text.isdigit():
        bot.send_message(message.chat.id, "⚠️ ID должен содержать только цифры! Попробуй ещё раз:")
        return

    roblox_id = int(text)
    data = load_data()

    if chat_id not in data:
        data[chat_id] = []

    if roblox_id in data[chat_id]:
        bot.send_message(message.chat.id, "⚠️ Этот игрок уже есть в твоём списке!", reply_markup=main_menu())
        waiting_for_id.discard(chat_id)
        return

    username = get_roblox_username(roblox_id)
    data[chat_id].append(roblox_id)
    save_data(data)
    waiting_for_id.discard(chat_id)

    bot.send_message(
        message.chat.id,
        f"✅ Игрок *{username}* (`{roblox_id}`) добавлен!\nБуду присылать уведомления об изменении его статуса.",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )


# ===================== ФОНОВЫЙ МОНИТОРИНГ =====================

def monitor_loop():
    print("🔄 Мониторинг запущен...")
    while True:
        try:
            data = load_data()

            all_ids = set()
            for players in data.values():
                all_ids.update(players)

            if all_ids:
                presences = get_roblox_presence(list(all_ids))
                presence_map = {p["userId"]: p for p in presences}

                for chat_id, player_ids in data.items():
                    if chat_id not in user_states:
                        user_states[chat_id] = {}

                    for roblox_id in player_ids:
                        presence = presence_map.get(roblox_id)
                        if not presence:
                            continue

                        current_status = presence.get("userPresenceType", 0)
                        current_place = presence.get("lastLocation", "")
                        last_status = user_states[chat_id].get(roblox_id)

                        # Первый раз — просто запоминаем, не шлём
                        if last_status is None:
                            user_states[chat_id][roblox_id] = current_status
                            continue

                        # Статус не изменился — пропускаем
                        if current_status == last_status:
                            continue

                        # Статус изменился — отправляем уведомление
                        username = get_roblox_username(roblox_id)

                        if current_status == 2:
                            game = current_place if current_place else "неизвестная игра"
                            msg = f"🚨 *{username}* зашёл в игру!\n🎮 {game}"
                        elif current_status == 1:
                            msg = f"🌐 *{username}* зашёл в сеть."
                        elif current_status == 3:
                            msg = f"🛠️ *{username}* открыл Roblox Studio."
                        elif current_status == 0:
                            msg = f"💤 *{username}* вышел офлайн."
                        else:
                            msg = f"🔄 *{username}*: {STATUS_NAMES.get(current_status, 'Неизвестно')}"

                        try:
                            bot.send_message(int(chat_id), msg, parse_mode="Markdown")
                        except Exception as e:
                            print(f"❌ Не смог отправить в {chat_id}: {e}")

                        user_states[chat_id][roblox_id] = current_status

        except Exception as e:
            print(f"❌ Ошибка в мониторинге: {e}")

        time.sleep(CHECK_INTERVAL)


# ===================== ЗАПУСК =====================

if __name__ == "__main__":
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    print("🤖 Бот запущен!")
    bot.infinity_polling()
