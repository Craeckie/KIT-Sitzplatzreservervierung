import datetime
import locale
import math
import os
import logging
import pickle
import re
from itertools import groupby

from telegram.ext import Updater, ConversationHandler, CallbackContext
from telegram.ext import CommandHandler, MessageHandler, Filters
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, ParseMode, ChatAction

from reservations import redis
from reservations.backend import Backend, Daytime, daytime_to_name, State, get_user_creds, remove_user_creds
from reservations.query import group_bookings, get_own_bookings

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

locale.setlocale(locale.LC_ALL, 'de_DE.UTF-8')
DATE_FORMAT = "%a, %d.%m."

request_kwargs = None
proxy = os.environ.get('PROXY')
if proxy:
    request_kwargs = {
        'proxy_url': proxy
    }
updater = Updater(token=os.environ.get('BOT_TOKEN'), request_kwargs=request_kwargs)
dispatcher = updater.dispatcher

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

FREE_SEAT_MARKUP = ['Heute', 'Morgen', 'In 2 Tagen', 'In 3 Tagen']
ACCOUNT_MARKUP = ['Reservierungen']
LOGIN_MARKUP = ['Login']
EXTRA_MARKUP = ['Zeiten', 'Statistiken']
CANCEL_MARKUP = ['Abbrechen']
NEW_LOGIN_MARKUP = ['Neu einloggen']

USERNAME, PASSWORD, CAPTCHA = range(3)


def check_login(update: Update, login_required=False):
    user_id = update.message.from_user.id
    cookies = b.login(user_id, login_required=login_required)
    if cookies:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, ACCOUNT_MARKUP, EXTRA_MARKUP])
    else:
        markup = ReplyKeyboardMarkup([FREE_SEAT_MARKUP, LOGIN_MARKUP])
    return cookies, markup


def start(update: Update, context: CallbackContext):
    update.message.reply_chat_action(ChatAction.TYPING)
    cookies, markup = check_login(update)
    context.bot.send_message(chat_id=update.effective_chat.id,
                             text="Willkommen beim KIT-Sitzplatzreservierungsbot!\n" +
                                  "Klicke auf die Knöpfe unten, um freie Plätze abzurufen.\n"
                                  "Um Plätze zu buchen musst du dich zuerst einloggen. Klicke dazu unten auf Login.",
                             reply_markup=markup)


def overview(update: Update, context: CallbackContext):
    update.message.reply_chat_action(ChatAction.TYPING)
    cookies, markup = check_login(update)
    try:
        text = update.message.text
        day_delta = 0 if text == 'Heute' else \
            1 if text == 'Morgen' else \
                2 if text == 'In 2 Tagen' else \
                    3
        date = datetime.datetime.today() + datetime.timedelta(days=day_delta)
        bookings = b.search_bookings(start_day=date,
                                     state=State.FREE)
        update.message.reply_chat_action(ChatAction.TYPING)
        grouped = group_bookings(bookings, b.areas)
        msg = f'<b>{date.strftime(DATE_FORMAT)}</b>\n'
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
    except Exception as e:
        msg = 'Leider ist ein Fehler aufgetreten:\n' + str(e)
    context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='HTML',
                             reply_markup=markup)


def booking(update: Update, context: CallbackContext):
    update.message.reply_chat_action(ChatAction.TYPING)
    text = update.message.text
    m = re.match(
        '^/B(?P<day_delta>[0-9])_(?P<daytime>[0-9])_(?P<room>[0-9]+)_(?P<room_id>[A-Z0-9]+)_(?P<seat>[A-Z0-9_]+)$',
        text)
    if m:
        cookies, markup = check_login(update, login_required=True)
        if cookies:
            user_id = update.message.from_user.id
            values = m.groupdict()
            values['seat'] = values['seat'].replace('_', ' ')
            success, msg = b.book_seat(user_id=user_id,
                                         cookies=cookies,
                                         **values)
            update.message.reply_text(
                (msg if msg else 'Erfolgreich gebucht!') if success else
                'Buchung ist leider fehlgeschlagen.' + (f'\nFehler: {msg}' if msg else ''),
                reply_markup=markup)
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
                row = [format_seat_command(values['day_delta'], values['daytime'], b) for b in
                       bookings[i * 3: (i + 1) * 3]]
                seat_markup.append(row)
            seat_markup.append(['Abbrechen'])
            context.bot.send_message(chat_id=update.effective_chat.id, text='Wähle einen Sitzplatz', parse_mode='HTML',
                                     reply_markup=ReplyKeyboardMarkup(seat_markup))
        else:
            m = re.match('^/C(?P<entry_id>[0-9]+)$', text)
            if m:
                entry_id = m.group('entry_id')
                user_id = update.message.from_user.id
                cookies, markup = check_login(update, login_required=True)
                success, error = b.cancel_reservation(user_id, entry_id, cookies)
                update.message.reply_text('Reservierung erfolgreich gelöscht.' if success else
                                          'Löschen fehlgeschlagen.' + (f'\nFehler: {error}' if error else ''),
                                          reply_markup=markup)
            else:
                context.bot.send_message(chat_id=update.effective_chat.id, text='Unbekannter Befehl', parse_mode='HTML',
                                         reply_markup=FREE_SEAT_MARKUP)


def reservations(update: Update, context: CallbackContext):
    update.message.reply_chat_action(ChatAction.TYPING)
    cookies, markup = check_login(update, login_required=True)
    update.message.reply_chat_action(ChatAction.TYPING)
    if cookies:
        # bookings = get_own_bookings(b, cookies)
        # if bookings:
        #     msg = '<u>Deine Reservierungen</u>\n'
        #     date_groups = groupby(bookings, key=lambda b: b['date'])
        #     for date, bookings in date_groups:

        #         msg += f'<pre>{date.strftime(DATE_FORMAT)}</pre>\n'
        #         for booking in bookings:
        #             msg += f"{daytime_to_name(booking['daytime'])} {b.areas[booking['room']]}: " \
        #                    f"Platz {booking['seat']['seat']} " \
        #                    f"/C{booking['seat']['entry_id']}\n"
        bookings = b.get_reservations(update.message.from_user.id, cookies)
        pin_message = False
        if bookings is None:
            msg = 'Es gab einen Fehler beim Öffnen der Reservierungen'
        elif bookings:
            msg = '<u>Deine Reservierungen</u>\n'
            last_date = None
            for booking in bookings:
                cur_date = booking['date']
                if last_date is not None:  # not first entry
                    msg += '\n'
                if cur_date != last_date:
                    msg += f'<pre>{cur_date}</pre>\n'
                if 'daytime' in booking:
                    daytime = booking["daytime"]
                    msg += f'<i>{daytime}</i>\n'
                msg += f"{booking['room']}: " \
                       f"Platz {booking['seat']} . Löschen: " \
                       f"/C{booking['id']}\n"
                last_date = cur_date
            pin_message = True
        else:
            msg = 'Du hast aktuell keine Reservierungen.'
        sent_message = update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        context.bot.unpin_all_chat_messages(chat_id=sent_message.chat_id)
        sent_message.pin(disable_notification=True)
    else:
        update.message.reply_text('Zuerst musst du dich einloggen. Klicke dazu unten auf Login.',
                                  reply_markup=markup)


def extras(update: Update, context: CallbackContext):
    update.message.reply_chat_action(ChatAction.TYPING)
    cookies, markup = check_login(update)
    update.message.reply_chat_action(ChatAction.TYPING)
    if update.message.text == 'Zeiten':
        html = str(b.get_times())
        print(html)
        update.message.reply_text(html, reply_markup=markup,
                                  parse_mode=ParseMode.HTML)
    elif update.message.text == 'Statistiken':
        msg = ''
        for d in range(0, 4):
            date = datetime.datetime.today() + datetime.timedelta(days=d)
            bookings = b.search_bookings(
                start_day=date,
                state=State.OCCUPIED)
            type_counts = {}
            room_counts = {}
            for booking in bookings:
                seat = booking['seat']
                occ_type = seat['occupier']
                if occ_type in type_counts.keys():
                    type_counts[occ_type] += 1
                else:
                    type_counts[occ_type] = 1
                room_id = int(seat['area'])
                room_name = 'KIT' if room_id in [19, 20, 21, 34, 35, 37] else \
                    'DHBW' if room_id == 32 else \
                        'HsKa' if room_id in [28, 29] else \
                            'KIT Nord' if room_id == 26 else \
                                'Unbekannt'
                if room_name in room_counts.keys():
                    room_counts[room_name] += 1
                else:
                    room_counts[room_name] = 1
            if msg:
                msg += '\n\n'
            msg += f'<b>{date.strftime(DATE_FORMAT)}</b>\n'
            total_count = sum(type_counts.values())
            msg += f'Insgesamt: {total_count}\n'
            msg += f'<u>Nach Uni/Hochschule:</u>\n'
            msg += '\n'.join(
                f'{t}: {count} ({round(count / total_count * 100, 1)}%)' for t, count in type_counts.items())
            msg += f'\n\n<u>Nach Raum:</u>\n'
            msg += '\n'.join(f'{room}: {count}' for room, count in room_counts.items())
        update.message.reply_text(msg, reply_markup=markup,
                                  parse_mode=ParseMode.HTML)


def format_seat_command(day_delta, daytime: int, booking:dict, reserved=False):
    prefix = 'C' if reserved else 'B'
    seat = booking['seat']['seat'].replace(' ', '_')
    return f"/{prefix}{day_delta}_{int(daytime)}_{booking['area']}_{booking['seat']['room_id']}_{seat}"


def get_user_key(update: Update, description: str):
    user_id = update.message.from_user.id
    return f'temp:{description}:{user_id}'


def login(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    creds = get_user_creds(user_id)
    if creds:
        photo, cookies = b.get_captcha()
        if photo:
            redis.set(get_user_key(update, 'login_cookies'), pickle.dumps(cookies))
            msg = 'Gib nun die Zeichen im Captcha ein.\nWenn du dich neu einloggen willst, klicke unten auf den Knopf.'
            markup = [NEW_LOGIN_MARKUP, CANCEL_MARKUP]
            update.message.reply_photo(photo=photo,
                                       caption=msg,
                                       reply_markup=ReplyKeyboardMarkup(markup))
            return CAPTCHA
        else:
            msg = 'Konnte Captcha nicht laden :('
            cookies, markup = check_login(update)
            update.message.reply_text(msg, reply_markup=markup)
    update.message.reply_text('Um dich einzuloggen musst du leider deine Kontodaten eingeben.\n'
                              'Es ist (soweit ich weiß) noch kein <a href="https://oauth.net/">Oauth</a> für die Sitzplatzreservierung implementiert.\n'
                              'Gib nun die Kontonummer von deinem Bibliotheks-Konto ein:',
                              reply_markup=ReplyKeyboardMarkup([CANCEL_MARKUP]),
                              parse_mode=ParseMode.HTML)
    return USERNAME


def login_username(update: Update, context: CallbackContext):
    text = update.message.text
    if text in CANCEL_MARKUP:
        return login_cancel(update, context)
    redis.set(get_user_key(update, 'login_username'), text)
    update.message.reply_text('Gib jetzt dein Passwort ein:', reply_markup=ReplyKeyboardMarkup([CANCEL_MARKUP]))
    return PASSWORD


def login_password(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    text = update.message.text
    if text in CANCEL_MARKUP:
        return login_cancel(update, context)
    update.message.reply_chat_action(ChatAction.TYPING)
    redis.set(get_user_key(update, 'login_password'), text)
    photo, cookies = b.get_captcha()
    if photo:
        redis.set(get_user_key(update, 'login_cookies'), pickle.dumps(cookies))
        msg = 'Gib nun die Zeichen im Captcha ein'
        markup = [CANCEL_MARKUP]
        update.message.reply_photo(photo=photo,
                                   caption=msg,
                                   reply_markup=ReplyKeyboardMarkup(markup))
        return CAPTCHA
    else:
        cookies, markup = check_login(update)
        update.message.reply_text('Konnte Captcha nicht laden :(', reply_markup=markup)
        return None


def login_captcha(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    creds = get_user_creds(user_id)
    update.message.reply_chat_action(ChatAction.TYPING)

    text = update.message.text
    if text in CANCEL_MARKUP:
        return login_cancel(update, context)
    elif text in NEW_LOGIN_MARKUP and creds:
        remove_user_creds(user_id)
        update.message.reply_text('Gib nun die Kontonummer von deinem Bibliotheks-Konto ein:',
                                  reply_markup=ReplyKeyboardMarkup([CANCEL_MARKUP]))
        return USERNAME
    elif creds:
        username = creds['user']
        password = creds['password']
    else:
        username = redis.get(get_user_key(update, 'login_username')).decode()
        password = redis.get(get_user_key(update, 'login_password')).decode()
    cookies_pickle = redis.get(get_user_key(update, 'login_cookies'))
    cookies = pickle.loads(cookies_pickle) if cookies_pickle else None
    captcha = update.message.text
    login_clean(update)
    cookies = b.login(user_id=user_id,
                      user=username,
                      password=password,
                      captcha=captcha,
                      cookies=cookies,
                      login_required=True)
    if cookies:
        update.message.reply_text('Erfolgreich eingeloggt!\n'
                                  'Die Nachrichten mit deinen Login-Daten kannst du jetzt löschen.',
                                  reply_markup=ReplyKeyboardMarkup([FREE_SEAT_MARKUP, ACCOUNT_MARKUP, EXTRA_MARKUP]))
    else:
        update.message.reply_text('Login fehlgeschlagen :(',
                                  reply_markup=ReplyKeyboardMarkup([FREE_SEAT_MARKUP, LOGIN_MARKUP]))

    return ConversationHandler.END


def login_clean(update: Update):
    redis.delete(get_user_key(update, 'login_username'))
    redis.delete(get_user_key(update, 'login_password'))
    redis.delete(get_user_key(update, 'login_cookies'))


def login_cancel(update: Update, context: CallbackContext):
    login_clean(update)
    update.message.reply_text('Login abgebrochen',
                              reply_markup=ReplyKeyboardMarkup([FREE_SEAT_MARKUP, LOGIN_MARKUP]))
    return ConversationHandler.END


dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(MessageHandler(Filters.text(FREE_SEAT_MARKUP) & (~Filters.command), overview))
dispatcher.add_handler(MessageHandler(Filters.command, booking))
dispatcher.add_handler(MessageHandler(Filters.text(ACCOUNT_MARKUP), reservations))
dispatcher.add_handler(MessageHandler(Filters.text(EXTRA_MARKUP), extras))

login_conv_handler = ConversationHandler(
    entry_points=[MessageHandler(Filters.text(LOGIN_MARKUP), login)],
    states={
        USERNAME: [MessageHandler(Filters.text & ~Filters.command, login_username)],
        PASSWORD: [MessageHandler(Filters.text & ~Filters.command, login_password)],
        CAPTCHA: [MessageHandler(Filters.text & ~Filters.command, login_captcha)]
    },
    fallbacks=[MessageHandler(Filters.text('Abbrechen'), login_cancel)]
)
dispatcher.add_handler(login_conv_handler)


def cancel_command(update: Update, context: CallbackContext):
    cookies, markup = check_login(update)
    login_clean(update)
    update.message.reply_text('Aktion abgebrochen.',
                              reply_markup=markup)

def unknown_command(update: Update, context: CallbackContext):
    if update.message.from_user.is_bot:
        return
    cookies, markup = check_login(update)
    update.message.reply_text('Unbekannter Befehl. Benutze die Buttons unten, um Funktionen aufzurufen.',
                              reply_markup=markup)


dispatcher.add_handler(MessageHandler(Filters.text(CANCEL_MARKUP), cancel_command))
dispatcher.add_handler(MessageHandler(~Filters.text(FREE_SEAT_MARKUP)
                                      & ~Filters.text(ACCOUNT_MARKUP)
                                      & ~Filters.text(LOGIN_MARKUP)
                                      & ~Filters.text(EXTRA_MARKUP)
                                      & ~Filters.command, unknown_command))

updater.start_polling()
