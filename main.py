# /usr/bin/python3
import datetime

from reservations.backend import Backend, Daytime
from reservations.query import free_seats

base_url = 'https://raumbuchung.bibliothek.kit.edu/sitzplatzreservierung/'

b = Backend(base_url)

results = free_seats(b, date=datetime.datetime.today() + datetime.timedelta(days=2),
                     daytimes=(Daytime.MORNING, Daytime.AFTERNOON))

for daytime, rooms in results.items():
    print(daytime)
    for room, seats in rooms.items():
        print(f'{room}: {len(seats)}')
    print()
