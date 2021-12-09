# KIT-Sitzplatzreservierung

## Getting Started

1. Create a [Telegram Bot](https://core.telegram.org/bots) using the [BotFather](https://t.me/botfather)
2. Get your token, which looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`

## Configuration
You need to set the following environment variables:
- **BOT_TOKEN** is your bot token

Optionally you can set a proxy:
- **PROXY** to e.g. `socks5h://127.0.0.1:9050`

## Run it!
Run `python3 telegram-bot.py`

For docker see the `docker-compose.yml`.

## API
See `reserverations/query.py` for two examples on getting bookings and free seats.
The central function is `search_bookings` in `reserverations/backend.py` which allows for easily getting a list of bookings of a time range. It can be filtered by daytime and location("areas").
