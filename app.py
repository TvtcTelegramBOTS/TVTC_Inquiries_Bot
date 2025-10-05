from flask import Flask
from threading import Thread
import telegram
from telegram.ext import Updater, CommandHandler

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=5000)

def start_bot():
    updater = Updater("7952874560:AAGfvHVSFGY9eid9DJhLMpwUzbYiDJwwusw", use_context=True)
    dispatcher = updater.dispatcher

    def start(update, context):
        update.message.reply_text("Hello, I am your bot!")

    dispatcher.add_handler(CommandHandler("start", start))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    # تشغيل Flask في Thread منفصل
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    # بدء بوت Telegram
    start_bot()
