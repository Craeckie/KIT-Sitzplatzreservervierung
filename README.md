# KIT-Sitzplatzreservervierung

## Getting Started

1. Create a [Telegram Bot](https://core.telegram.org/bots) using the [BotFather](https://t.me/botfather)
2. Get your token, which looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`

## Configuration
You need to set the following environment variables:
- **BOT_TOKEN** is your bot token
- **SP_USER** is your library account number
- **SP_PASS** is your library account password

Optionally you can set a proxy:
- **PROXY** to e.g. `socks5h://127.0.0.1:9050`

## Run it!
Run `python3 telegram-bot.py`

For docker see the `docker-compose.yml`.
