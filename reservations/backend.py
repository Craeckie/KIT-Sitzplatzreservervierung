import datetime
import json
import math
import os
import pickle
import urllib
from enum import IntEnum
from urllib.parse import urljoin

import bs4
import requests
from dateutil import rrule

from . import redis


class Backend:
    def __init__(self, base_url):
        self.base_url = base_url
        self.proxy = os.environ.get('PROXY')

        self.areas = self.get_areas()

    def get_areas(self):
        r = self.get_request('/sitzplatzreservierung/')
        b = bs4.BeautifulSoup(r.text, 'html.parser')

        area_div = b.find('div', id='dwm_areas')
        areas = {}
        for li in area_div.find_all('li'):
            name = li.text.strip()
            url = urllib.parse.urlparse(li.a.get('href'))
            params = urllib.parse.parse_qs(url.query)
            number = ''.join(params['area'])
            areas[number] = name
        return areas

    def get_times(self):
        r = self.get_request('/sitzplatzreservierung/')
        b = bs4.BeautifulSoup(r.text, 'html.parser')

        time_div = b.find('font', style='color: #000000')
        print([tag.string for tag in time_div.children])
        strings = time_div.find_all(lambda tag:
                                    tag.string or
                                    tag.name == 'a',
                                    text=True)
        print(strings)
        for tag in time_div.contents:
            print(f'{tag}')
        return '\n'.join([
            str(tag) if isinstance(tag, bs4.element.Tag) else tag.string.strip()
            for tag in time_div.contents
            if (not tag.name or tag.name not in ['br', 'font'])
               and tag.string.strip()])

    def login(self, user_id, user=None, password=None, login_required=False):
        cookies_key = f'login-cookies:{user_id}'
        cookies_pickle = redis.get(cookies_key)
        cookies = pickle.loads(cookies_pickle) if cookies_pickle else None
        if cookies and not login_required:
            return cookies
        else:
            res = self.get_request('admin.php', cookies=cookies)
            if 'Buchungsübersicht von' in res.text:
                return res.cookies

            # Renew cookies using creds
            creds_key = f'login-creds:{user_id}'
            if not user or not password:
                creds_json = redis.get(creds_key)
                creds = json.loads(creds_json) if creds_json else None
                if creds:
                    user = creds['user']
                    password = creds['password']
            if user and password:

                # Get the cookies
                res = self.get_request('admin.php')
                login_res = self.post_request('admin.php',
                                              data={
                                                  'NewUserName': user,
                                                  'NewUserPassword': password,
                                                  'returl': self.base_url,
                                                  'TargetURL': self.base_url,
                                                  'Action': 'SetName'
                                              }, allow_redirects=False)
                if login_res.status_code == 200:
                    print(f'Login failed: {user}')
                    print(login_res.text)
                else:
                    print(f'Logged in {user}')
                    creds_json = {
                        'user': user,
                        'password': password
                    }
                    redis.set(creds_key, json.dumps(creds_json))
                    redis.set(cookies_key, pickle.dumps(login_res.cookies))
                    return login_res.cookies
            return None

    def get_day_url(self, date, area):
        return f'day.php?year={date.year}&month={date.month}&day={date.day}&area={area}'

    def get_room_entries(self, date, area, cookies=None):
        url = self.get_day_url(date, area)

        times = {}
        if not cookies:
            redis_key = f'room_entries:{date.date()}:{area}'
            cached_data = redis.get(redis_key)
            times_data = json.loads(cached_data) if cached_data else None
            if times_data:
                for daytime, entries in times_data.items():
                    for entry in entries:
                        entry['state'] = State(entry['state'])
                    daytime = Daytime(int(daytime))
                    times[daytime] = entries

        if not times:
            r = self.get_request(url, cookies=cookies)
            b = bs4.BeautifulSoup(r.text, 'html.parser')

            table = b.find(id="day_main")

            labels = [(list(t.strings)[1], t.attrs['data-room'])
                      for t in list(table.thead.children)[1]
                      if type(t) == bs4.element.Tag
                      and 'data-room' in t.attrs]

            rows = [r for r in table.tbody.children
                    if type(r) == bs4.element.Tag
                    and ('even_row' in r.attrs["class"] or 'odd_row' in r.attrs["class"])]
            rows[0].td.find(class_='celldiv').text.strip()

            times = {}
            for row in rows:
                row_entries = []
                col_index = 0
                row_label = 'N/A'
                for column in row.find_all('td'):
                    classes = column.attrs["class"]
                    if 'row_labels' in classes:
                        row_label = column.find(class_='celldiv').text.strip()
                        daytime = Daytime.MORNING if row_label == 'vormittags' else \
                            Daytime.AFTERNOON if row_label == 'nachmittags' else \
                                Daytime.EVENING

                        continue
                    state = 'new' in classes and State.FREE or \
                            'private' in classes and State.OCCUPIED or \
                            'writable' in classes and State.MINE or \
                            State.UNKNOWN
                    occupier = state in [State.FREE, State.MINE] and None or \
                               'I' in classes and 'Interne Buchungen' or \
                               'K' in classes and 'KIT Studenten' or \
                               'D' in classes and 'DHBW Studenten' or \
                               'H' in classes and 'HsKa Studenten' or \
                               'G' in classes and 'Private Buchungen' or \
                               'P' in classes and 'Personal' or \
                               'special'
                    div = column.div
                    entry_id = div.attrs['data-id'] if 'data-id' in div.attrs else None

                    label = labels[col_index]
                    row_entries.append({
                        'area': area,
                        'seat': label[0],
                        'room_id': label[1],
                        'state': state,
                        'occupier': occupier,
                        'entry_id': entry_id
                    })
                    col_index += 1
                times[daytime] = row_entries

            expiry_time = 300
            if date.date() == datetime.datetime.now().date():
                expiry_time = 15
            redis.set(redis_key, json.dumps(times), ex=expiry_time)

        return times

    def get_day_entries(self, date, areas=None, cookies=None):
        entries = {}
        for area in areas if areas else [a for a in self.areas.keys()]:
            room_entries = self.get_room_entries(date, area, cookies=cookies)
            entries.update({
                area: room_entries
            })
        return entries

    def search_bookings(self, start_day=datetime.datetime.today() + datetime.timedelta(days=1),
                        day_count=1,
                        state=None,
                        daytimes=None,
                        areas=None,
                        cookies=None):
        bookings = []

        def time_bookings(time_entries, daytime):
            for seat in time_entries:
                if not state or seat["state"] == state:
                    bookings.append({
                        'date': date,
                        'daytime': daytime,
                        'seat': seat,
                        'room': room_name,
                        'area': seat['area']
                    })

        for date in rrule.rrule(rrule.DAILY, count=day_count, dtstart=start_day):
            day_entries = self.get_day_entries(date, areas=areas, cookies=cookies)
            for room_name, room_entries in day_entries.items():
                if daytimes is None:
                    for time_name, time_entries in room_entries.items():
                        time_bookings(time_entries, time_name)
                else:
                    if isinstance(daytimes, Daytime):
                        daytimes = [daytimes]
                    elif all(isinstance(d, int) for d in daytimes):
                        daytimes = [Daytime(d) for d in daytimes]
                    for daytime in daytimes:
                        time_bookings(room_entries[daytime], daytime)

        return bookings

    def book_seat(self, user_id, day_delta, daytime, room, seat, room_id, cookies):
        date = datetime.datetime.today() + datetime.timedelta(days=int(day_delta))
        creds_key = f'login-creds:{user_id}'
        creds_json = redis.get(creds_key)
        creds = json.loads(creds_json) if creds_json else None
        user = creds['user']
        daytime = int(daytime)
        seconds = 43200 if daytime == Daytime.MORNING else \
            43260 if daytime == Daytime.AFTERNOON else \
                43320 if daytime == Daytime.EVENING else \
                    0
        if seconds == 0:
            raise AttributeError('Invalid daytime!')
        data = {
            'name': user,
            'description': daytime_to_name(int(daytime)).lower() + '+',
            'start_day': date.day,
            'start_month': date.month,
            'start_year': date.year,
            'start_seconds': str(seconds),
            'end_day': date.day,
            'end_month': date.month,
            'end_year': date.year,
            'end_seconds': str(seconds),
            'area': room,
            'rooms[]': room_id,
            'type': 'K',
            'confirmed': '1',
            'returl': self.get_day_url(date, room),
            'create_by': user,
            'rep_id': '0',
            'edit_type': 'series'
        }
        data = {k: str(v) for k, v in data.items()}
        res = self.get_request(
                    f'edit_entry.php?area={room}&room={room_id}&period=0'
                    f'&year={date.year}&month={date.month}&day={date.day}', cookies=cookies)
        res = self.post_request('edit_entry_handler.php', data={**data,
                                                                'ajax': '1'})
        check_result = None
        try:
            check_result = res.json()
        except:
            pass
        res = self.post_request('edit_entry_handler.php', data=data, allow_redirects=False)
        if res.status_code == 302:
            print(f"Erfolgreich gebucht: {data}")
            return True, None
        else:
            page = bs4.BeautifulSoup(res.text, 'html.parser')

            content = page.find(id="contents")
            msg = check_result['rules_broken'][0] \
                if check_result and 'rules_broken' in check_result and check_result['rules_broken'] else None
            if not msg:
                msg = content.get_text() if content else None

            return False, msg

        try:
            res = json.loads(res.text)
            if 'valid_booking' in res and res['valid_booking']:
                print(f"Erfolgreich gebucht: {data}")
                return True
            else:
                print(f"Buchen fehlgeschlagen: {data}")
                return False

        except:
            print(f"Buchen fehlgeschlagen: {data}")
            return False

    def cancel_reservation(self, user_id, entry_id, cookies):
        creds = get_user_creds(user_id)
        user = creds['user']

        now = datetime.datetime.now()
        url = ('del_entry.php?' +
               f'id={entry_id}&series=0&returl=report.php?'
               f'from_day={now.day}&from_month={now.month}&from_year={now.year}'
               f'&to_day=1&to_month=12&to_year=2030'
               f'&areamatch=&roommatch=&namematch=&descrmatch=&creatormatch={user}'
               f'&match_private=2&match_confirmed=2'
               f'&output=0&output_format=0&sortby=r&sumby=d&phase=2&datatable=1')
        res = self.get_request(url, allow_redirects=False)
        if res.status_code == 302:
            return True, None
        else:
            return False, None

    def get_reservations(self, user_id, cookies):
        creds = get_user_creds(user_id)
        user = creds['user']

        now = datetime.datetime.now()
        end = datetime.datetime(year=2030, month=12, day=1)
        res = self.get_request('report.php', cookies=cookies,
                               params={
                                   'from_day': now.day,
                                   'from_month': now.month,
                                   'from_year': now.year,
                                   'to_day': end.day,
                                   'to_month': end.month,
                                   'to_year': end.year,
                                   'areamatch': '',
                                   'roommatch': '',
                                   'namematch': '',
                                   'descrmatch': '',
                                   'creatormatch': user,
                                   'match_private': 2,
                                   'match_confirmed': 2,
                                   'output': 0,
                                   'output_format': 0,
                                   'sortby': 'd',
                                   'sumby': 'd',
                                   'datatable': 1,
                                   'phase': "2,2",
                                   'ajax': 1,
                                   '_': now.timestamp()
                               })
        if res.status_code != 200:
            return None

        data = json.loads(res.text)
        entries = []
        for j_entries in data['aaData']:
            entry = {}
            links = j_entries[0]
            b = bs4.BeautifulSoup(links, 'html.parser')
            entry['id'] = b.a.attrs['data-id']
            entry['room'] = j_entries[1]
            entry['seat'] = j_entries[2]

            b = bs4.BeautifulSoup(j_entries[3], 'html.parser')
            entry['date'] = b.get_text().title()
            entries.append(entry)
        return entries

        # b = bs4.BeautifulSoup(res.text, 'html.parser')
        # table = b.find(id="report_table")

        # rows = [r for r in table.tbody.children
        #         if type(r) == bs4.element.Tag]
        # entries = []
        # for row in rows:
        #     entry = {}
        #     columns = row.find_all('td')
        #     entry_links = columns[0].a
        #     entry['id'] = entry_links.attrs['data-id']
        #     entry['room'] = columns[1].get_text()
        #     entry['seat'] = columns[2].get_text()
        #     entry['date'] = columns[3].get_text()
        #     entries.append(entry)
        # return entries

    def get_request(self, *args, **kwargs):
        return self.request(*args, method='GET', **kwargs)

    def post_request(self, *args, **kwargs):
        return self.request(*args, method='POST', **kwargs)

    def request(self, suburl, method='GET', cookies=None, params=None, **kwargs):
        url = urljoin(self.base_url, suburl)
        session = requests.session()
        if self.proxy:
            session.proxies.update({
                'http': self.proxy,
                'https': self.proxy
            })
        if cookies:
            session.cookies = cookies

        res = session.request(method=method, url=url, params=params, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:78.0) Gecko/20100101 Firefox/78.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'de_DE,en;q=0.5'
        }, **kwargs)
        # Overwrite old cookies with new cookies
        session.cookies.update(res.cookies)
        res.cookies = session.cookies
        return res


def daytime_to_name(daytime):
    if daytime == Daytime.MORNING:
        return 'Vormittags'
    elif daytime == Daytime.AFTERNOON:
        return 'Nachmittags'
    elif daytime == Daytime.EVENING:
        return 'Abends'
    else:
        raise AttributeError('Invalid daytime: {daytime}')


def get_user_creds(user_id):
    creds_key = f'login-creds:{user_id}'
    creds_json = redis.get(creds_key)
    creds = json.loads(creds_json) if creds_json else None
    return creds


class State(IntEnum):
    FREE = 1
    OCCUPIED = 2
    MINE = 3
    UNKNOWN = 4


class Daytime(IntEnum):
    MORNING = 1
    AFTERNOON = 2
    EVENING = 3
