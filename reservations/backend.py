import datetime
import json
import os
import pickle
import urllib
from enum import Enum

import bs4
import requests
from dateutil import rrule


class Backend:
    def __init__(self, base_url):
        self.base_url = base_url
        proxy = os.environ.get('PROXY')
        if proxy:
            self.session.proxies.update({
                'http': proxy,
                'https': proxy
            })

        self.areas = self.get_areas()

    def get_areas(self):
        r = requests.get(self.base_url)
        b = bs4.BeautifulSoup(r.text, 'html.parser')

        area_div = b.find('div', id='dwm_areas')
        areas = []
        for li in area_div.find_all('li'):
            name = li.text.strip()
            url = urllib.parse.urlparse(li.a.get('href'))
            params = urllib.parse.parse_qs(url.query)
            number = ''.join(params['area'])
            areas.append({
                'name': name,
                'number': number
            })
        return areas

    def login(self, user_id, user=None, password=None):
        cookies_key = f'login-creds:{user_id}'
        cookies_pickle = redis.get(cookies_key)
        cookies = pickle.loads(cookies_pickle) if cookies_pickle else None

        # Check if session still valid

        # Renew cookies using creds
        if not user or not password:
            creds_key = f'login-creds:{user_id}'
            creds_json = redis.get(creds_key)
            creds = json.loads(creds_json) if creds_json else None
            if creds:
                user = creds['user']
                password = creds['password']
        if user and password:
            login_url = urllib.parse.urljoin(base=self.base_url, url='admin.php')

            # Create new session and get the cookies
            session = requests.session()
            session.get(login_url)
            login_res = session.post(login_url,
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
                redis.set(cookies_key, pickle.dumps(session.cookies))
                return session.cookies
        return None

    def get_room_entries(self, date, area, cookies=None):
        url = urllib.parse.urljoin(base=self.base_url,
                                   url=f'day.php?year={date.year}&month={date.month}&day={date.day}&area={area}')
        session = requests.session()
        if cookies:
            session.cookies = cookies
        r = session.get(url)
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
                           'I' in classes and 'internal' or \
                           'K' in classes and 'student' or \
                           'special'

                label = labels[col_index]
                row_entries.append({
                    'seat': label[0],
                    'room_id': label[1],
                    'state': state,
                    'occupier': occupier
                })
                col_index += 1
            times[daytime] = row_entries

        return times

    def get_day_entries(self, date, areas=None, cookies=None):
        entries = {}
        for area in areas if areas else self.areas:
            room_entries = self.get_room_entries(date, area['number'], cookies=cookies)
            entries.update({
                area['name']: room_entries
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
                    for daytime in daytimes:
                        time_bookings(room_entries[daytime], daytime)

        return bookings


def daytime_to_name(daytime):
    if daytime == Daytime.MORNING:
        return 'Vormittags'
    elif daytime == Daytime.AFTERNOON:
        return 'Nachmittags'
    elif daytime == Daytime.EVENING:
        return 'Abends'
    else:
        raise AttributeError('Invalid daytime: {daytime}')

class State(Enum):
    FREE = 1
    OCCUPIED = 2
    MINE = 3
    UNKNOWN = 4


class Daytime(Enum):
    MORNING = 1
    AFTERNOON = 2
    EVENING = 3