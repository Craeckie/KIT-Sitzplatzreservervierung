import datetime
from itertools import groupby

from reservations.backend import State, Daytime


def get_own_bookings(backend):
    start_day = datetime.datetime.today() + datetime.timedelta(days=1)
    bookings = backend.search_bookings(start_day, day_count=3, state=State.MINE)
    return bookings


def free_seats(backend, date=datetime.datetime.today() + datetime.timedelta(days=1), daytimes=None):
    bookings = backend.search_bookings(start_day=date, state=State.FREE, daytimes=daytimes)
    results = {}
    if isinstance(daytimes, Daytime):
        daytimes = [daytimes]
    elif daytimes is None:
        daytimes = [Daytime.MORNING, Daytime.AFTERNOON, Daytime.EVENING]

    for daytime in daytimes:
        cur_bookings = filter(lambda b: b['daytime'] == daytime, bookings)
        room_groups = groupby(cur_bookings, key=lambda b: b['room'])
        room_bookings = {
            room: list(bookings) for room, bookings in room_groups
        }
        results[daytime] = room_bookings
    return results

