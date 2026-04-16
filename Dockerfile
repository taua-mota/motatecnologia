FROM python:3.12-alpine

WORKDIR /app

COPY index.html ./index.html
COPY styles.css ./styles.css
COPY dashboard.html ./dashboard.html
COPY server.py ./server.py
COPY aniversario ./aniversario

ENV PORT=80

EXPOSE 80

CMD ["python", "server.py"]
