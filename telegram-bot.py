import datetime
import os
import logging
from telegram.ext import Updater
from telegram.ext import CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup

from reservations.backend import Backend, Daytime, daytime_to_name
from reservations.query import free_seats

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                     level=logging.INFO)

updater = Updater(token=os.environ.get('BOT_TOKEN'))
dispatcher = updater.dispatcher

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

FREE_SEAT_MARKUP = ReplyKeyboardMarkup([
    ['Heute', 'Morgen', 'In 2 Tagen', 'In 3 Tagen']
])

def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Willkommen beim KIT-Sitzplatzreservierungsbot!\n" +
                                  "Klicke auf die Knöpfe unten, um freie Plätze abzurufen",
                             reply_markup=FREE_SEAT_MARKUP)
def echo(update, context):
    day_delta = 0 if update.message.text == 'Heute' else \
                1 if update.message.text == 'Morgen' else \
                2 if update.message.text == 'In 2 Tagen' else \
                3
    results = free_seats(b, date=datetime.datetime.today() + datetime.timedelta(days=day_delta))
    msg = ''
    for daytime, rooms in results.items():
        msg += f'<pre>{daytime_to_name(daytime)}</pre>\n'
        for room, seats in rooms.items():
            msg += f'{room}: {len(seats)}'
            if len(seats) < 5:
                msg += ' (' + ', '.join([s['seat']['seat'] for s in seats]) + ')'
            msg += '\n'
        msg += '\n'
    context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='HTML', reply_markup=FREE_SEAT_MARKUP)

start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)
echo_handler = MessageHandler(Filters.text & (~Filters.command), echo)
dispatcher.add_handler(echo_handler)

updater.start_polling()