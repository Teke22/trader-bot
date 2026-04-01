import ccxt
import pandas as pd
import ta
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import os
import time
import json
from flask import Flask
import threading

# ===== настройки =====
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04
TRADE_SIZE = 1000

# ===== загрузка .env =====
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PORT = int(os.getenv("PORT", 10000))

# Flask app для поддержки Web Service
app_flask = Flask(__name__)

exchange = ccxt.binance()

symbols = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'BNB/USDT', 'XRP/USDT',
    'ADA/USDT', 'DOGE/USDT',
    'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT',
    'LTC/USDT','TRX/USDT','ATOM/USDT','UNI/USDT',
    'APT/USDT','ARB/USDT','OP/USDT','SUI/USDT',
    'NEAR/USDT','FIL/USDT'
]

# ===== данные =====
positions = {
    "aggressive": {},
    "smart": {}
}

trade_stats = {
    "aggressive": {"profit": 0, "trades": 0, "wins": 0},
    "smart": {"profit": 0, "trades": 0, "wins": 0}
}

stats = {
    "total": 0,
    "buy": 0,
    "sell": 0
}

trades_history = []

# ===== сохранение =====
DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "data.json")

def save_data():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    data = {
        "positions": positions,
        "trade_stats": trade_stats,
        "stats": stats,
        "trades_history": trades_history
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Данные сохранены в {DATA_FILE}")

def load_data():
    global positions, trade_stats, stats, trades_history
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            positions = data.get("positions", positions)
            trade_stats = data.get("trade_stats", trade_stats)
            stats = data.get("stats", stats)
            trades_history = data.get("trades_history", [])
            print(f"Данные загружены из {DATA_FILE}")
    except FileNotFoundError:
        print("Нет сохранённых данных, создаю новый файл")
        save_data()
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")

# ===== кнопки =====
keyboard = ReplyKeyboardMarkup(
    [
        ["📊 Статистика", "🔄 Проверить рынок"],
        ["📈 Состояние рынка", "📉 RSI сейчас"],
        ["📜 История сделок"]
    ],
    resize_keyboard=True
)

# ===== логика =====
async def check_market(bot):
    print("Проверка рынка...")

    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])

            df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()

            macd = ta.trend.MACD(df['close'])
            df['macd'] = macd.macd()
            df['signal'] = macd.macd_signal()

            df['ema'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()

            rsi = df['rsi'].iloc[-1]

            macd_now = df['macd'].iloc[-1]
            signal_now = df['signal'].iloc[-1]

            price = df['close'].iloc[-1]

            aggressive_signal = None
            smart_signal = None

            if rsi < 30:
                aggressive_signal = "BUY"

            if rsi < 35 and macd_now > signal_now:
                smart_signal = "BUY"
            elif rsi > 65 and macd_now < signal_now:
                smart_signal = "SELL"

            for mode, signal in [("aggressive", aggressive_signal), ("smart", smart_signal)]:

                if not signal:
                    continue

                if signal == "BUY" and symbol not in positions[mode]:

                    amount = TRADE_SIZE / price

                    positions[mode][symbol] = {
                        "entry": price,
                        "amount": amount,
                        "stop": price * (1 - STOP_LOSS),
                        "take": price * (1 + TAKE_PROFIT),
                        "time": time.strftime("%Y-%m-%d %H:%M:%S")
                    }

                    await bot.send_message(
                        CHAT_ID,
                        f"🔥 {mode.upper()} BUY {symbol}\nЦена: {price:.2f}"
                    )

                elif mode == "smart" and signal == "SELL" and symbol in positions[mode]:
                    pos = positions[mode][symbol]

                    profit = (price - pos["entry"]) * pos["amount"]

                    trade_stats[mode]["profit"] += profit
                    trade_stats[mode]["trades"] += 1

                    if profit > 0:
                        trade_stats[mode]["wins"] += 1

                    trades_history.append({
                        "symbol": symbol,
                        "result": f"{mode.upper()} SIGNAL SELL",
                        "profit": profit,
                        "buy_time": pos["time"],
                        "sell_time": time.strftime("%Y-%m-%d %H:%M:%S")
                    })

                    await bot.send_message(
                        CHAT_ID,
                        f"💰 {mode.upper()} SELL {symbol}\nPnL: {profit:.2f}"
                    )

                    del positions[mode][symbol]

                if symbol in positions[mode]:
                    pos = positions[mode][symbol]
                    exit_trade = None

                    if price <= pos["stop"]:
                        exit_trade = "❌ STOP LOSS"
                    elif price >= pos["take"]:
                        exit_trade = "🎯 TAKE PROFIT"

                    if exit_trade:
                        profit = (price - pos["entry"]) * pos["amount"]

                        trade_stats[mode]["profit"] += profit
                        trade_stats[mode]["trades"] += 1

                        if profit > 0:
                            trade_stats[mode]["wins"] += 1

                        trades_history.append({
                            "symbol": symbol,
                            "result": f"{mode.upper()} {exit_trade}",
                            "profit": profit,
                            "buy_time": pos["time"],
                            "sell_time": time.strftime("%Y-%m-%d %H:%M:%S")
                        })

                        await bot.send_message(
                            CHAT_ID,
                            f"{mode.upper()} {exit_trade}\n{symbol}\nPnL: {profit:.2f}"
                        )

                        del positions[mode][symbol]

                save_data()

            await asyncio.sleep(1)

        except Exception as e:
            print(f"Ошибка {symbol}:", e)

# ===== RSI =====
async def show_rsi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "📉 RSI по рынку:\n\n"

    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])

            rsi = ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1]

            icon = "⚪"
            if rsi < 30:
                icon = "🟢"
            elif rsi > 70:
                icon = "🔴"

            message += f"{icon} {symbol} — RSI: {rsi:.2f}\n"

        except:
            message += f"{symbol} ошибка\n"

    await update.message.reply_text(message)

# ===== рынок =====
async def market_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "📈 Состояние рынка:\n\n"

    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])

            df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
            df['ema'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()

            rsi = df['rsi'].iloc[-1]
            price = df['close'].iloc[-1]
            ema = df['ema'].iloc[-1]

            state = "⚪ Нейтрально"
            if rsi < 30:
                state = "🟢 BUY зона"
            elif rsi > 70:
                state = "🔴 SELL зона"

            message += f"{symbol}\nЦена: {price:.2f}\nRSI: {rsi:.2f}\nEMA: {ema:.2f}\n{state}\n---\n"

        except:
            message += f"{symbol} ошибка\n"

    await update.message.reply_text(message)

# ===== история =====
async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trades_history:
        await update.message.reply_text("📜 История пустая")
        return

    message = "📜 Последние сделки:\n\n"

    for trade in trades_history[-10:][::-1]:
        message += (
            f"{trade['symbol']}\n"
            f"{trade['result']}\n"
            f"PnL: {trade['profit']:.2f}\n"
            f"{trade['buy_time']} → {trade['sell_time']}\n"
            f"---\n"
        )

    await update.message.reply_text(message)

# ===== статистика =====
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    def calc(mode):
        t = trade_stats[mode]["trades"]
        w = trade_stats[mode]["wins"]
        p = trade_stats[mode]["profit"]
        wr = (w / t * 100) if t > 0 else 0

        return f"{mode.upper()}:\n💰 {p:.2f}\n📈 {t}\n🎯 {wr:.1f}%\n\n"

    msg = "📊 Стратегии:\n\n"
    msg += calc("aggressive")
    msg += calc("smart")

    await update.message.reply_text(msg)

# ===== команды =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Бот запущен 🚀", reply_markup=keyboard)

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Проверяю рынок...")
    await check_market(context.bot)

# ===== кнопки =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📊 Статистика":
        await stats_cmd(update, context)
    elif text == "🔄 Проверить рынок":
        await manual_check(update, context)
    elif text == "📈 Состояние рынка":
        await market_status(update, context)
    elif text == "📉 RSI сейчас":
        await show_rsi(update, context)
    elif text == "📜 История сделок":
        await show_history(update, context)

# ===== Flask маршруты =====
@app_flask.route('/')
def index():
    return "Trading Bot is running!", 200

@app_flask.route('/health')
def health():
    return "OK", 200

# ===== Запуск Flask в отдельном потоке =====
def run_flask():
    app_flask.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ===== Запуск бота (в главном потоке) =====
async def run_bot():
    load_data()
    
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))

    async def loop_task(context):
        await check_market(context.bot)

    application.job_queue.run_repeating(loop_task, interval=100, first=5)

    print("Бот запущен 🚀")
    await application.run_polling()

# ===== Точка входа =====
if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Запускаем бота в главном потоке
    asyncio.run(run_bot())