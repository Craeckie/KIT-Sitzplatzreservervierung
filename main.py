# /usr/bin/python3
import datetime

from reservations.backend import Backend, Daytime, State
from reservations.query import group_bookings

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

daytimes = (Daytime.MORNING, Daytime.AFTERNOON)
bookings = b.search_bookings(start_day=datetime.datetime.today() + datetime.timedelta(days=2),
                                   state=State.FREE,
                                   daytimes=daytimes)
grouped = group_bookings(bookings, daytimes)

for daytime, rooms in results.items():
    print(daytime)
    for room, seats in rooms.items():
        print(f'{room}: {len(seats)}')
    print()
