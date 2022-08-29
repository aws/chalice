FROM python:3.6-buster

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y libpq-dev gcc && \
    apt-get clean && \
    pip install --upgrade setuptools pip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /chalice

COPY . .

RUN pip install -e ".[event-file-poller]" && \
    pip install -r requirements-dev.txt && \
    pip install -r requirements-docs.txt
