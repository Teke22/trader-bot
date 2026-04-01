import ccxt
import pandas as pd
import ta
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
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

exchange = ccxt.binance()

symbols = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT',
    'BNB/USDT', 'XRP/USDT', 'ADA/USDT', 'DOGE/USDT',
    'AVAX/USDT', 'LINK/USDT', 'MATIC/USDT', 'LTC/USDT',
    'TRX/USDT', 'ATOM/USDT', 'UNI/USDT', 'APT/USDT',
    'ARB/USDT', 'OP/USDT', 'SUI/USDT', 'NEAR/USDT', 'FIL/USDT'
]

# ===== данные (только в памяти) =====
positions = {
    "aggressive": {},
    "smart": {}
}

trade_stats = {
    "aggressive": {"profit": 0, "trades": 0, "wins": 0},
    "smart": {"profit": 0, "trades": 0, "wins": 0}
}

# ===== кнопки =====
keyboard = ReplyKeyboardMarkup(
    [
        ["📊 Статистика", "🔄 Проверить рынок"],
        ["📈 Состояние рынка", "📉 RSI сейчас"]
    ],
    resize_keyboard=True
)

# ===== HTTP сервер для Render =====
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Trading Bot is running!')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass  # Отключаем логи HTTP сервера

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    server.serve_forever()

# ===== логика бота =====
async def check_market(bot):
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])

            df['rsi'] = ta.momentum.RSIIndicator(df['close']).rsi()
            macd = ta.trend.MACD(df['close'])
            df['macd'] = macd.macd()
            df['signal'] = macd.macd_signal()

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
                        "time": time.strftime("%H:%M:%S")
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
                    await bot.send_message(
                        CHAT_ID,
                        f"💰 {mode.upper()} SELL {symbol}\nPnL: {profit:.2f}"
                    )
                    del positions[mode][symbol]

                if symbol in positions[mode]:
                    pos = positions[mode][symbol]
                    exit_trade = None
                    if price <= pos["stop"]:
                        exit_trade = "STOP LOSS"
                    elif price >= pos["take"]:
                        exit_trade = "TAKE PROFIT"

                    if exit_trade:
                        profit = (price - pos["entry"]) * pos["amount"]
                        trade_stats[mode]["profit"] += profit
                        trade_stats[mode]["trades"] += 1
                        if profit > 0:
                            trade_stats[mode]["wins"] += 1
                        await bot.send_message(
                            CHAT_ID,
                            f"{mode.upper()} {exit_trade}\n{symbol}\nPnL: {profit:.2f}"
                        )
                        del positions[mode][symbol]

            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Ошибка {symbol}: {e}")

async def show_rsi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "📉 RSI по рынку:\n\n"
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])
            rsi = ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1]
            icon = "🟢" if rsi < 30 else "🔴" if rsi > 70 else "⚪"
            message += f"{icon} {symbol} — RSI: {rsi:.2f}\n"
        except:
            message += f"❌ {symbol} ошибка\n"
    await update.message.reply_text(message)

async def market_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = "📈 Состояние рынка:\n\n"
    for symbol in symbols:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
            df = pd.DataFrame(bars, columns=['time','open','high','low','close','volume'])
            rsi = ta.momentum.RSIIndicator(df['close']).rsi().iloc[-1]
            price = df['close'].iloc[-1]
            state = "🟢 BUY зона" if rsi < 30 else "🔴 SELL зона" if rsi > 70 else "⚪ Нейтрально"
            message += f"{symbol}\n💰 {price:.2f}\n📊 RSI: {rsi:.2f}\n{state}\n---\n"
        except:
            message += f"❌ {symbol} ошибка\n"
    await update.message.reply_text(message)

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    def calc(mode):
        t = trade_stats[mode]["trades"]
        w = trade_stats[mode]["wins"]
        p = trade_stats[mode]["profit"]
        wr = (w / t * 100) if t > 0 else 0
        return f"*{mode.upper()}*\n💰 {p:.2f}\n📈 {t}\n🎯 {wr:.1f}%\n\n"
    msg = "📊 *Статистика стратегий:*\n\n" + calc("aggressive") + calc("smart")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Торговый бот запущен*\n\n"
        "📊 Статистика - показывает прибыль\n"
        "🔄 Проверить рынок - ручной запуск\n"
        "📈 Состояние рынка - RSI по всем монетам\n"
        "📉 RSI сейчас - быстрый RSI",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

async def manual_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Проверяю рынок...")
    await check_market(context.bot)

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

# ===== Запуск =====
async def main():
    print("🚀 Запуск торгового бота...")
    
    # Запускаем HTTP сервер в фоне
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print(f"✅ HTTP сервер запущен на порту {PORT}")
    
    # Запускаем Telegram бота
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT, handle_message))
    
    async def loop_task(context):
        await check_market(context.bot)
    
    application.job_queue.run_repeating(loop_task, interval=100, first=5)
    
    print("✅ Бот запущен и работает!")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())