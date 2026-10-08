FROM python:3.13-alpine

WORKDIR /app
COPY loggen.py ./
COPY loggen ./loggen
COPY profiles ./profiles

ENV LOGGEN_OUT=/out \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/loggen.py"]
CMD ["live"]
