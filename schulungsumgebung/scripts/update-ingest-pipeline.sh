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
curl -X PUT "http://es01:9200/_ingest/pipeline/logs-elasticsearch.server-1.19.0-pipeline-json" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H 'Content-Type: application/json' \
  -d '{
  "description": "Pipeline for parsing the Elasticsearch 8.0 server log file in JSON format.",
  "processors": [
    {
      "rename": {
        "field": "message",
        "target_field": "_ecs_json_message",
        "ignore_missing": true
      }
    },
    {
      "json": {
        "field": "_ecs_json_message",
        "add_to_root": true,
        "add_to_root_conflict_strategy": "merge",
        "allow_duplicate_keys": true,
        "if": "ctx.containsKey('"'"'_ecs_json_message'"'"')",
        "on_failure": [
          {
            "rename": {
              "field": "_ecs_json_message",
              "target_field": "message",
              "ignore_missing": true
            }
          },
          {
            "set": {
              "field": "error.message",
              "value": "Error while parsing JSON",
              "override": false
            }
          }
        ]
      }
    },
    {
      "remove": {
        "field": "_ecs_json_message",
        "ignore_missing": true
      }
    },
    {
      "dot_expander": {
        "field": "*",
        "override": true
      }
    },
    {
      "join": {
        "field": "error.stack_trace",
        "separator": "\n",
        "if": "ctx.error?.stack_trace instanceof Collection"
      }
    },
    {
      "drop": {
        "if": "ctx.event.dataset != '"'"'elasticsearch.server'"'"'"
      }
    },
    {
      "set": {
        "field": "service.type",
        "value": "elasticsearch"
      }
    },
    {
      "grok": {
        "field": "message",
        "pattern_definitions": {
          "GREEDYMULTILINE": "(.|\\n)*",
          "INDEXNAME": "[a-zA-Z0-9_.-]*",
          "GC_ALL": "\\\\[gc\\\\]\\\\[%{NUMBER:elasticsearch.server.gc.overhead_seq}\\\\] overhead, spent \\\\[%{NUMBER:elasticsearch.server.gc.collection_duration.time:float}%{DATA:elasticsearch.server.gc.collection_duration.unit}\\\\] collecting in the last \\\\[%{NUMBER:elasticsearch.server.gc.observation_duration.time:float}%{DATA:elasticsearch.server.gc.observation_duration.unit}\\\\]",
          "GC_YOUNG": "\\\\[gc\\\\]\\\\[young\\\\]\\\\[%{NUMBER:elasticsearch.server.gc.young.one}\\\\]\\\\[%{NUMBER:elasticsearch.server.gc.young.two}\\\\]%{SPACE}%{GREEDYMULTILINE:message}"
        },
        "patterns": [
          "%{GC_ALL}",
          "%{GC_YOUNG}",
          "((\\\\[%{INDEXNAME:_parsed_index_name}\\\\]|\\\\[%{INDEXNAME:_parsed_index_name}\\\\/%{DATA:_parsed_index_id}\\\\]))?%{SPACE}%{GREEDYMULTILINE}"
        ],
        "ignore_failure": true
      }
    },
    {
      "date": {
        "field": "@timestamp",
        "target_field": "@timestamp",
        "formats": ["ISO8601"],
        "ignore_failure": true
      }
    },
    {
      "rename": {
        "if": "ctx?.elasticsearch?.index?.name == null",
        "field": "_parsed_index_name",
        "target_field": "elasticsearch.index.name",
        "ignore_missing": true
      }
    },
    {
      "remove": {
        "field": "_parsed_index_name",
        "ignore_missing": true
      }
    },
    {
      "rename": {
        "if": "ctx?.elasticsearch?.index?.id == null",
        "field": "_parsed_index_id",
        "target_field": "elasticsearch.index.id",
        "ignore_missing": true
      }
    },
    {
      "remove": {
        "field": "_parsed_index_id",
        "ignore_missing": true
      }
    },
    {
      "set": {
        "field": "elasticsearch.cluster.name",
        "copy_from": "cluster.name",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "set": {
        "field": "elasticsearch.cluster.uuid",
        "copy_from": "cluster.uuid",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "set": {
        "field": "log.level",
        "copy_from": "level",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "set": {
        "field": "elasticsearch.node.name",
        "copy_from": "node.name",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "set": {
        "field": "elasticsearch.node.id",
        "copy_from": "node.id",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "set": {
        "field": "elasticsearch.component",
        "copy_from": "component",
        "ignore_empty_value": true,
        "ignore_failure": true
      }
    },
    {
      "remove": {
        "field": ["cluster", "node", "level", "component"],
        "ignore_missing": true
      }
    }
  ],
  "on_failure": [
    {
      "set": {
        "field": "error.message",
        "value": "{{ _ingest.on_failure_message }}"
      }
    }
  ],
  "_meta": {
    "managed_by": "fleet",
    "managed": true,
    "package": {
      "name": "elasticsearch"
    }
  }
}'

echo ""
echo "Pipeline updated successfully!"

