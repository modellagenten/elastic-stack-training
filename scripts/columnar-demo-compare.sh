#!/bin/bash

# Vergleicht die drei Demo-Data-Streams (standard / logsdb / logsdb_columnar):
#   1. Speicherbedarf nach Force-Merge
#   2. Speicher pro Feld und Datenstruktur (_disk_usage)
#   3. Laufzeiten identischer ES|QL-Abfragen
#   4. _source desselben Dokuments
#
# Voraussetzung: columnar-demo-setup.sh und Befüllung mit "loggen.py backfill --profile columnar-demo".
# Benötigt: curl, jq
#
# Aufruf: ./scripts/columnar-demo-compare.sh [--skip-merge] [--repeat N]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -z "${ELASTIC_PASSWORD}" ] && [ -f "${SCRIPT_DIR}/../.env" ]; then
  ELASTIC_PASSWORD=$(grep -E '^ELASTIC_PASSWORD=' "${SCRIPT_DIR}/../.env" | cut -d= -f2- | tr -d '"')
fi
ES_URL="${ES_URL:-http://localhost:9200}"
AUTH="elastic:${ELASTIC_PASSWORD}"
MODES="standard logsdb columnar"
SKIP_MERGE=0
REPEAT=3

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-merge) SKIP_MERGE=1 ;;
    --repeat) REPEAT="$2"; shift ;;
  esac
  shift
done

if ! command -v jq > /dev/null; then
  echo "Dieses Skript benötigt jq (macOS: brew install jq, Alpine: apk add jq)."
  exit 1
fi

es() {
  curl -s -u "${AUTH}" -H 'Content-Type: application/json' "$@"
}

ds() { echo "logs-demo.$1-default"; }

backing_index() {
  es "${ES_URL}/_data_stream/$(ds "$1")" | jq -r '.data_streams[0].indices[-1].index_name'
}

header() {
  echo
  echo "================================================================================"
  echo "$1"
  echo "================================================================================"
}

for m in ${MODES}; do
  if [ "$(backing_index "${m}")" = "null" ]; then
    echo "Data Stream $(ds "${m}") fehlt. Erst columnar-demo-setup.sh und den Backfill ausführen."
    exit 1
  fi
done

if [ "${SKIP_MERGE}" = "0" ]; then
  header "Vorbereitung: Refresh und Force-Merge auf 1 Segment (kann einige Minuten dauern)"
  for m in ${MODES}; do
    es -X POST "${ES_URL}/$(ds "${m}")/_refresh" > /dev/null
    printf "  %-30s " "$(ds "${m}")"
    es -X POST "${ES_URL}/$(ds "${m}")/_forcemerge?max_num_segments=1" | jq -c '._shards'
  done
fi

header "1. Speicherbedarf (primäre Shards)"
printf "  %-30s %-16s %12s %14s %14s\n" "Data Stream" "index.mode" "Dokumente" "Größe (MB)" "Bytes/Dok."
for m in ${MODES}; do
  idx=$(backing_index "${m}")
  mode=$(es "${ES_URL}/${idx}/_settings?flat_settings=true&include_defaults=true" \
    | jq -r --arg i "${idx}" '.[$i] | (.settings["index.mode"] // .defaults["index.mode"] // "standard")')
  es "${ES_URL}/${idx}/_stats/docs,store" | jq -r --arg ds "$(ds "${m}")" --arg mode "${mode}" '
    ._all.primaries as $p
    | [$ds, $mode, $p.docs.count, ($p.store.size_in_bytes / 1048576), ($p.store.size_in_bytes / ([$p.docs.count,1]|max))]
    | "  \(.[0] | . + " " * (30 - length)) \(.[1] | . + " " * (16 - length)) \(.[2] | tostring | " " * (12 - length) + .) \(.[3] * 10 | round / 10 | tostring | " " * (14 - length) + .) \(.[4] * 10 | round / 10 | tostring | " " * (14 - length) + .)"'
done

header "2. Speicher pro Datenstruktur und Top-Felder (_disk_usage)"
for m in ${MODES}; do
  idx=$(backing_index "${m}")
  echo
  echo "  $(ds "${m}")"
  es -X POST "${ES_URL}/${idx}/_disk_usage?run_expensive_tasks=true" | jq -r --arg i "${idx}" '
    .[$i] as $d
    | def mb: . / 1048576 * 10 | round / 10;
      def col(w): tostring | " " * (w - length) + .;
    "    gesamt: \($d.store_size_in_bytes | mb) MB",
    "    \("Feld" | . + " " * (28 - length)) \("gesamt" | col(9)) \("_source" | col(9)) \("invIndex" | col(9)) \("docVals" | col(9)) \("points" | col(9))  (MB)",
    ( $d.fields | to_entries
      | map(select((.key | startswith("_") | not) or .key == "_source" or .key == "_id" or .key == "_seq_no"))
      | sort_by(-.value.total_in_bytes) | .[:12][]
      | "    \(.key | . + " " * ([28 - length, 1] | max)) \(.value.total_in_bytes | mb | col(9)) \(.value.stored_fields_in_bytes | mb | col(9)) \(.value.inverted_index.total_in_bytes | mb | col(9)) \(.value.doc_values_in_bytes | mb | col(9)) \(.value.points_in_bytes | mb | col(9))" )'
done

run_esql() {
  # $1 = Abfrage mit Platzhalter TARGET
  local query="${1//TARGET/$2}"
  es -X POST "${ES_URL}/_query?format=json" -d "$(jq -n --arg q "${query}" '{query: $q}')"
}

header "3. ES|QL-Laufzeiten in ms (${REPEAT} Durchläufe, erster Lauf mit kaltem Cache)"
SAMPLE_ID=$(run_esql 'FROM TARGET | SORT @timestamp DESC | LIMIT 1 | KEEP event.id' "$(ds standard)" | jq -r '.values[0][0]')
QUERIES=(
  "Aggregation pro Host|FROM TARGET | STATS c = COUNT(*) BY host.name | SORT c DESC | LIMIT 5"
  "Filter auf Statuscode|FROM TARGET | WHERE http.response.status_code >= 500 | STATS c = COUNT(*) BY service.name | SORT c DESC"
  "Letzte Stunde, Ø Dauer|FROM TARGET | WHERE @timestamp > NOW() - 1 hour | STATS avg_ms = AVG(event.duration) / 1000000 BY service.name | SORT avg_ms DESC | LIMIT 5"
  "Volltextsuche message|FROM TARGET | WHERE MATCH(message, \"payment\") | STATS c = COUNT(*)"
  "Punktabfrage event.id|FROM TARGET | WHERE event.id == \"${SAMPLE_ID}\" | KEEP @timestamp, host.name, message"
)
printf "  %-26s" "Abfrage"
for m in ${MODES}; do printf " %22s" "${m}"; done
echo
for entry in "${QUERIES[@]}"; do
  label="${entry%%|*}"
  query="${entry#*|}"
  printf "  %-26s" "${label}"
  for m in ${MODES}; do
    times=""
    for _ in $(seq "${REPEAT}"); do
      t=$(run_esql "${query}" "$(ds "${m}")" | jq -r '.took // "ERR"')
      times="${times}${times:+/}${t}"
    done
    printf " %22s" "${times}"
  done
  echo
done
echo
echo "  Abfragen (TARGET = Data Stream):"
for entry in "${QUERIES[@]}"; do echo "    ${entry#*|}"; done

header "4. Dasselbe Dokument in allen drei Modi (tags mit Duplikat, links als Array of Objects)"
DOC_ID=$(run_esql 'FROM TARGET | WHERE MV_COUNT(tags) >= 4 AND links.trace_id IS NOT NULL | SORT @timestamp DESC | LIMIT 1 | KEEP event.id' \
  "$(ds columnar)" | jq -r '.values[0][0] // empty')
if [ -z "${DOC_ID}" ]; then
  DOC_ID=$(es "${ES_URL}/$(ds standard)/_search" -d '{"size":1,"_source":["event.id"],"query":{"exists":{"field":"links.trace_id"}}}' \
    | jq -r '.hits.hits[0]._source.event.id')
fi
echo
echo "  ES|QL liest Doc Values - Reihenfolge und Duplikate von tags (event.id = ${DOC_ID}):"
for m in ${MODES}; do
  printf "    %-10s %s\n" "${m}" "$(run_esql "FROM TARGET | WHERE event.id == \"${DOC_ID}\" | KEEP tags" "$(ds "${m}")" | jq -c '.values[0][0]')"
done
for m in ${MODES}; do
  echo
  echo "  --- _source in $(ds "${m}") ---"
  es "${ES_URL}/$(ds "${m}")/_search" -d '{"size": 1, "query": {"term": {"event.id": "'"${DOC_ID}"'"}}}' \
    | jq '.hits.hits[0]._source'
done

cat <<'EOF'

Diskussionsimpulse:
  - Wie stark unterscheiden sich Größe und Bytes pro Dokument? Welche Felder dominieren?
  - Wo liegt bei columnar der Speicher (doc values) und wo fehlt er (inverted index, _source)?
  - Welche Abfrage wird mit columnar langsamer, welche schneller? Warum (Punktabfrage ohne Index)?
  - Was bedeutet das flache _source und der Verlust der Gruppierung in "links" für eure Anwendungen?
EOF
