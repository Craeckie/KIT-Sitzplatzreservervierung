import datetime
import os
import logging
import re

from telegram.ext import Updater
from telegram.ext import CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup

from reservations.backend import Backend, Daytime, daytime_to_name, State
from reservations.query import group_bookings

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

updater = Updater(token=os.environ.get('BOT_TOKEN'))
dispatcher = updater.dispatcher

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

FREE_SEAT_MARKUP = ['Heute', 'Morgen', 'In 2 Tagen', 'In 3 Tagen']
ACCOUNT_MARKUP = ['Reservierungen']
LOGIN_MARKUP = ['Login']


def start(update, context):
    user_id = update.message.from_user.id
    cookies = b.login(user_id)
    if cookies:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, ACCOUNT_MARKUP])
    else:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, LOGIN_MARKUP])
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Willkommen beim KIT-Sitzplatzreservierungsbot!\n" +
                                  "Klicke auf die Knöpfe unten, um freie Plätze abzurufen",
                             reply_markup=markup)


def overview(update, context):
    text = update.message.text
    if [text] == ACCOUNT_MARKUP:  # Own Reservations
        pass
    else:
        day_delta = 0 if text == 'Heute' else \
                    1 if text == 'Morgen' else \
                    2 if text == 'In 2 Tagen' else \
                    3
        bookings = b.search_bookings(start_day=datetime.datetime.today() + datetime.timedelta(days=day_delta),
                                     state=State.FREE)
        grouped = group_bookings(bookings)
        msg = ''
        for daytime, rooms in grouped.items():
            msg += f'<pre>{daytime_to_name(daytime)}</pre>\n'
            for room, seats in rooms.items():
                msg += f'{room}: {len(seats)}'
                if len(seats) <= 3:
                    msg += ' (' + ', '.join(
                        [f"/B{day_delta}_{daytime}_{room}_{s['seat']['seat']}" for s in seats]) + ')'
                else:
                    msg += f' /B{day_delta}_{daytime}_{room}'
                msg += '\n'
            msg += '\n'
        context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='HTML',
                                 reply_markup=FREE_SEAT_MARKUP)


def booking(update, context):
    text = update.message.text
    m = re.match('/B(?P<day_delta>[0-9])_(?P<daytime>[0-9])_(?P<room>[0-9]+)_(?P<seat>[0-9]+)', text)
    if m:
        pass
    else:
        m = re.match('/B(?P<day_delta>[0-9])_(?P<daytime>[0-9])_(?P<room>[0-9]+)', text)
        if m:
            values = m.groupdict()
            bookings = b.search_bookings(
                start_day=datetime.datetime.today() + datetime.timedelta(days=values['day_delta']),
                state=State.FREE,
                daytimes=[values['daytime']],
                areas=[values['room']])
            print(bookings)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text='Unbekannter Befehl', parse_mode='HTML',
                                     reply_markup=FREE_SEAT_MARKUP)


start_handler = CommandHandler('start', start)
dispatcher.add_handler(start_handler)
overview_handler = MessageHandler(Filters.text & (~Filters.command), overview)
dispatcher.add_handler(overview_handler)
booking_handler = MessageHandler(Filters.command, booking)
dispatcher.add_handler(booking_handler)

updater.start_polling()
