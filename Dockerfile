FROM python:3-alpine

#RUN mkdir /sitzplatz-bot
COPY ./ /opt/bot
WORKDIR /opt/bot

ENV VIRTUAL_ENV=/opt/bot/env
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin/:$PATH"


RUN pip install --upgrade pip && \
    pip install -r requirements.txt

CMD ["python3", "telegram-bot.py"]
