FROM python:3.12-alpine

RUN apk add --no-cache bash docker-cli
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py matrix_ops.py cli.py ./
COPY templates ./templates
COPY static ./static

RUN mkdir -p /data/tokens

EXPOSE 8090

CMD ["gunicorn","-b","0.0.0.0:8090","-w","1","--threads","4","--timeout","600","app:app"]
