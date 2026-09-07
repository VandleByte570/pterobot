FROM python:3.10

WORKDIR /opt/pterobot

COPY . .

RUN python -m pip install --upgrade -r requirements.txt

CMD [ "python", "-m", "pterobot.main" ]
