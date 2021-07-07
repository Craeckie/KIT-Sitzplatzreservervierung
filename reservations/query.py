import datetime
from itertools import groupby

from reservations.backend import State, Daytime


def get_own_bookings(backend, cookies):
    start_day = datetime.datetime.today()
    bookings = backend.search_bookings(start_day, day_count=4, state=State.MINE, cookies=cookies)
    return bookings


def group_bookings(bookings, areas, daytimes=None):
    results = {}
    if isinstance(daytimes, Daytime):
        daytimes = [daytimes]
    elif daytimes is None:
        daytimes = [Daytime.MORNING, Daytime.AFTERNOON, Daytime.EVENING]
    for daytime in daytimes:
        cur_bookings = filter(lambda b: b['daytime'] == daytime, bookings)
        room_groups = groupby(cur_bookings, key=lambda b: b['room'])
        room_bookings = {
            areas[room]: list(bookings) for room, bookings in room_groups
        }
        results[daytime] = room_bookings
    return results

