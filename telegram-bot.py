import datetime
import math
import os
import logging
import re
from itertools import groupby

from telegram.ext import Updater, ConversationHandler, CallbackContext
from telegram.ext import CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, ParseMode

from reservations import redis
from reservations.backend import Backend, Daytime, daytime_to_name, State
from reservations.query import group_bookings, get_own_bookings

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

updater = Updater(token=os.environ.get('BOT_TOKEN'))
dispatcher = updater.dispatcher

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

FREE_SEAT_MARKUP = ['Heute', 'Morgen', 'In 2 Tagen', 'In 3 Tagen']
ACCOUNT_MARKUP = ['Reservierungen']
LOGIN_MARKUP = ['Login']

USERNAME, PASSWORD = range(2)

def check_login(update):
    user_id = update.message.from_user.id
    cookies = b.login(user_id)
    if cookies:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, ACCOUNT_MARKUP])
    else:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, LOGIN_MARKUP])
    return cookies, markup

def start(update, context):
    cookies, markup = check_login(update)
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Willkommen beim KIT-Sitzplatzreservierungsbot!\n" +
                                  "Klicke auf die Knöpfe unten, um freie Plätze abzurufen",
                             reply_markup=markup)


def overview(update, context):
    cookies, markup = check_login(update)
    text = update.message.text
    day_delta = 0 if text == 'Heute' else \
                1 if text == 'Morgen' else \
                2 if text == 'In 2 Tagen' else \
                3
    bookings = b.search_bookings(start_day=datetime.datetime.today() + datetime.timedelta(days=day_delta),
                                 state=State.FREE)
    grouped = group_bookings(bookings, b.areas)
    msg = ''
    for daytime, rooms in grouped.items():
        msg += f'<pre>{daytime_to_name(daytime)}</pre>\n'
        for room, seats in rooms.items():
            msg += f'{room}: {len(seats)}'
            if len(seats) <= 3:
                msg += ' (' + ', '.join(
                    [format_seat_command(day_delta, daytime, s) for s in seats]) + ')'
            else:
                area = seats[0]['area']
                msg += f' /B{day_delta}_{int(daytime)}_{area}'
            msg += '\n'
        msg += '\n'
    context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='HTML',
                                 reply_markup=markup)


def booking(update, context):
    text = update.message.text
    m = re.match('^/B(?P<day_delta>[0-9])_(?P<daytime>[0-9])_(?P<room>[0-9]+)_(?P<seat>[A-Z0-9]+)_(?P<room_id>[A-Z0-9]+)$', text)
    if m:
        cookies, markup = check_login(update)
        if cookies:
            user_id = update.message.from_user.id
            values = m.groupdict()
            b.book_seat(user_id=user_id,
                        cookies=cookies,
                        **values)
        else:
            update.message.reply_text('Zuerst musst du dich einloggen. Klicke dazu unten auf Login.',
                              reply_markup=markup)
    else:
        m = re.match('^/B(?P<day_delta>[0-9])_(?P<daytime>[0-9])_(?P<room>[0-9]+)$', text)
        if m:
            values = m.groupdict()
            bookings = b.search_bookings(
                start_day=datetime.datetime.today() + datetime.timedelta(days=int(values['day_delta'])),
                state=State.FREE,
                daytimes=[int(values['daytime'])],
                areas=[int(values['room'])])
            seat_markup = []
            row_count = math.ceil(len(bookings) / 3)
            for i in range(0, row_count):
                row = [format_seat_command(values['day_delta'], values['daytime'], b) for b in bookings[i * 3: (i+1) * 3]]
                seat_markup.append(row)
            seat_markup.append(['Abbrechen'])
            context.bot.send_message(chat_id=update.effective_chat.id, text='Wähle einen Sitzplatz', parse_mode='HTML',
                                     reply_markup=ReplyKeyboardMarkup(seat_markup))
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text='Unbekannter Befehl', parse_mode='HTML',
                                     reply_markup=FREE_SEAT_MARKUP)

def reservations(update: Update, context: CallbackContext):
    cookies, markup = check_login(update)
    if cookies:
        bookings = get_own_bookings(b, cookies)
        if bookings:
            msg = 'Deine Reservierungen:\n'
            date_groups = groupby(bookings, key=lambda b: b['date'])
            for date, bookings in date_groups:
                msg += f'<pre>{date.date()}</pre>\n'
                for booking in bookings:
                    msg += f"{daytime_to_name(booking['daytime'])} {b.areas[booking['room']]}: " \
                           f"Platz {booking['seat']['seat']} " \
                           f"{format_seat_command(0, booking['daytime'], booking, reserverd=True)}\n"
        else:
            msg = 'Du hast aktuell keine Reservierungen.'
        update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    else:
        update.message.reply_text('Zuerst musst du dich einloggen. Klicke dazu unten auf Login.',
                                  reply_markup=markup)


def format_seat_command(day_delta, daytime, booking, reserverd=False):
    prefix = 'C' if reserverd else 'B'
    return f"/{prefix}{day_delta}_{int(daytime)}_{booking['area']}_{booking['seat']['seat']}_{booking['seat']['room_id']}"

def get_login_key(update):
    user_id = update.message.from_user.id
    return f'temp:login_user:{user_id}'

def login(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    update.message.reply_text('Um dich einzuloggen musst du leider deine Kontodaten eingeben.\n'
                              'Es ist (soweit ich weiß) noch kein <a href="https://oauth.net/">Oauth</a> für die Sitzplatzreservierung implementiert.\n'
                              'Gib die Kontonummer von deinem Bibiliotheks-Konto ein:',
                              reply_markup=ReplyKeyboardRemove(),
                              parse_mode=ParseMode.HTML)
    return USERNAME

def login_username(update: Update, context: CallbackContext):
    redis.set(get_login_key(update), update.message.text)
    update.message.reply_text('Gib nun dein Passwort ein:', reply_markup=ReplyKeyboardRemove())
    return PASSWORD

def login_password(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = redis.get(get_login_key(update)).decode()
    redis.delete(get_login_key(update))
    password = update.message.text
    cookies = b.login(user_id, username, password)
    if cookies:
        update.message.reply_text('Erfolgreich eingeloggt!\n'
                                  'Die Nachrichten mit deinen Login-Daten kannst du jetzt löschen.',
                                  reply_markup=ReplyKeyboardMarkup([FREE_SEAT_MARKUP,ACCOUNT_MARKUP]))
    else:
        update.message.reply_text('Login fehlgeschlagen :(', reply_markup=ReplyKeyboardMarkup([FREE_SEAT_MARKUP,LOGIN_MARKUP]))

    return ConversationHandler.END

def login_cancel(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    redis.delete(f'temp:login_user:{user_id}')
    return ConversationHandler.END


dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(MessageHandler(Filters.text(FREE_SEAT_MARKUP) & (~Filters.command), overview))
dispatcher.add_handler(MessageHandler(Filters.command, booking))
dispatcher.add_handler(MessageHandler(Filters.text(ACCOUNT_MARKUP), reservations))

login_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(Filters.text(LOGIN_MARKUP), login)],
    states={
        USERNAME: [MessageHandler(Filters.text & ~Filters.command, login_username)],
        PASSWORD: [MessageHandler(Filters.text & ~Filters.command, login_password)]
    },
    fallbacks=[MessageHandler(Filters.text('Abbrechen'), login_cancel)]
)
dispatcher.add_handler(login_conv_handler)


def unknown_command(update: Update, context: CallbackContext):
    cookies, markup = check_login(update)
    update.message.reply_text('Unbekannter Befehl. Benutze die Buttons unten, um Funktionen aufzurufen.',
                              reply_markup=markup)


dispatcher.add_handler(MessageHandler(~Filters.text(FREE_SEAT_MARKUP)
                                      & ~Filters.text(ACCOUNT_MARKUP)
                                      & ~Filters.text(LOGIN_MARKUP)
                                      & ~Filters.command, unknown_command))

updater.start_polling()
