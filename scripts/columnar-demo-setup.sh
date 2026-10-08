#!/bin/bash

# Legt drei Data Streams mit identischem Mapping, aber unterschiedlichem index.mode an:
#   logs-demo.standard-default  -> standard
#   logs-demo.logsdb-default    -> logsdb
#   logs-demo.columnar-default  -> logsdb_columnar (Preview ab 9.5)
# Anschließend werden sie mit dem Generator gleich befüllt (siehe Ausgabe am Ende).
#
# Aufruf vom Host:      ./scripts/columnar-demo-setup.sh [--reset]
# Andere Umgebung:      ES_URL=https://... ELASTIC_PASSWORD=... ./scripts/columnar-demo-setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -z "${ELASTIC_PASSWORD}" ] && [ -f "${SCRIPT_DIR}/../.env" ]; then
  ELASTIC_PASSWORD=$(grep -E '^ELASTIC_PASSWORD=' "${SCRIPT_DIR}/../.env" | cut -d= -f2- | tr -d '"')
fi
ES_URL="${ES_URL:-http://localhost:9200}"
AUTH="elastic:${ELASTIC_PASSWORD}"
MODES="standard logsdb columnar"

es() {
  curl -s -u "${AUTH}" -H 'Content-Type: application/json' "$@"
  echo
}

index_mode() {
  case "$1" in
    columnar) echo "logsdb_columnar" ;;
    *) echo "$1" ;;
  esac
}

echo "Prüfe Elasticsearch unter ${ES_URL} ..."
until curl -s -u "${AUTH}" "${ES_URL}/_cluster/health" | grep -q '"status":"green"\|"status":"yellow"'; do
  echo "Warte auf Elasticsearch..."
  sleep 5
done
es "${ES_URL}/_license?filter_path=license.type,license.status"

if [ "$1" = "--reset" ]; then
  echo "Lösche vorhandene Demo-Data-Streams ..."
  for m in ${MODES}; do
    code=$(curl -s -o /dev/null -w '%{http_code}' -u "${AUTH}" -X DELETE "${ES_URL}/_data_stream/logs-demo.${m}-default")
    case "${code}" in
      200) echo "  logs-demo.${m}-default gelöscht" ;;
      404) echo "  logs-demo.${m}-default nicht vorhanden" ;;
      *)   echo "  logs-demo.${m}-default: HTTP ${code}" ;;
    esac
  done
fi

echo "Component Template loggen-demo@mappings (gleiches Mapping für alle drei Modi) ..."
es -X PUT "${ES_URL}/_component_template/loggen-demo@mappings" -d '{
  "template": {
    "settings": {
      "number_of_shards": 1,
      "number_of_replicas": 0
    },
    "mappings": {
      "properties": {
        "@timestamp":            { "type": "date" },
        "message":               { "type": "text" },
        "event.id":              { "type": "keyword" },
        "event.dataset":         { "type": "keyword" },
        "event.category":        { "type": "keyword" },
        "event.outcome":         { "type": "keyword" },
        "event.action":          { "type": "keyword" },
        "event.duration":        { "type": "long" },
        "host.name":             { "type": "keyword" },
        "host.ip":               { "type": "ip" },
        "service.name":          { "type": "keyword" },
        "log.level":             { "type": "keyword" },
        "source.ip":             { "type": "ip" },
        "destination.ip":        { "type": "ip" },
        "http.request.method":   { "type": "keyword" },
        "http.response.status_code": { "type": "short" },
        "http.response.body.bytes":  { "type": "long" },
        "url.path":              { "type": "keyword" },
        "url.original":          { "type": "keyword" },
        "user_agent.original":   { "type": "keyword" },
        "user.name":             { "type": "keyword" },
        "trace.id":              { "type": "keyword" },
        "span.id":               { "type": "keyword" },
        "error.message":         { "type": "text" },
        "error.stack_trace":     { "type": "text" },
        "tags":                  { "type": "keyword" }
      }
    }
  }
}'

for m in ${MODES}; do
  mode=$(index_mode "${m}")
  echo "Index Template logs-demo.${m} (index.mode=${mode}) ..."
  es -X PUT "${ES_URL}/_index_template/logs-demo.${m}" -d '{
    "index_patterns": ["logs-demo.'"${m}"'-*"],
    "data_stream": {},
    "priority": 500,
    "composed_of": ["loggen-demo@mappings"],
    "template": {
      "settings": { "index.mode": "'"${mode}"'" }
    },
    "_meta": { "description": "Columnar-Demo der Elastic-Stack-Schulung" }
  }'
done

cat <<EOF

Fertig. Jetzt die drei Data Streams mit identischen Daten befüllen (gleicher Seed), z. B.:

  python3 generator/loggen.py backfill --profile columnar-demo --from now-1d --events 1000000 \\
    --es ${ES_URL}

oder im Container:

  docker compose run --rm loggen backfill --profile columnar-demo --from now-1d --events 1000000 \\
    --es http://es01:9200

Danach vergleichen:

  ./scripts/columnar-demo-compare.sh
EOF
