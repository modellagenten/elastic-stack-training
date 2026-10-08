#!/bin/bash

# Script to update the Elasticsearch server logs ingest pipeline
# This fixes the JSON parsing issue in Stack Monitoring

set -e

echo "Waiting for Elasticsearch to be ready..."
until curl -s -u "elastic:${ELASTIC_PASSWORD}" http://es01:9200/_cluster/health | grep -q '"status":"green"\|"status":"yellow"'; do
  echo "Waiting for Elasticsearch..."
  sleep 5
done

echo "Elasticsearch is ready. Updating ingest pipeline..."

# Update the logs-elasticsearch.server pipeline
curl -X PUT "http://es01:9200/_component_template/metrics-elasticsearch.stack_monitoring.index@custom" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -d '{
  "template": {
    "mappings": {
      "properties": {
        "elasticsearch": {
          "properties": {
            "index": {
              "properties": {
                "name": {
                  "type": "keyword",
                  "index": true,
                  "time_series_dimension": true
                }
              }
            }
          }
        }
      }
    }
  }
}'

echo ""
echo "Component template updated successfully!"

