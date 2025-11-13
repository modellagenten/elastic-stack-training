#!/bin/sh
set -e

echo "=== Fleet Agent Policies Setup via REST API ==="
echo "Waiting for Kibana to be ready..."

# Warte bis Kibana verfügbar ist
MAX_RETRIES=60
RETRY_COUNT=0

until curl -s -u "elastic:${ELASTIC_PASSWORD}" "http://kibana:5601/api/status" > /dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "ERROR: Kibana did not become ready in time"
    exit 1
  fi
  echo "Waiting for Kibana... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 5
done

echo "Kibana is ready!"

# Warte noch etwas, damit Fleet vollständig initialisiert ist
echo "Waiting for Fleet to initialize..."
sleep 10

# Initiiere Fleet Setup (falls noch nicht geschehen)
echo "Initiating Fleet setup..."
curl -s -X POST "http://kibana:5601/api/fleet/setup" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" || true

sleep 5

# === 1. Erstelle Agent Policy für Elasticsearch und Kibana Monitoring ===
echo ""
echo "Creating Agent Policy: elasticsearch-kibana..."

POLICY_RESPONSE=$(curl -s -X POST "http://kibana:5601/api/fleet/agent_policies?sys_monitoring=true" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "elasticsearch-kibana-policy",
    "name": "elasticsearch-kibana",
    "description": "Policy for monitoring Elasticsearch and Kibana",
    "namespace": "default",
    "monitoring_enabled": ["logs", "metrics"],
    "inactivity_timeout": 1209600,
    "is_protected": false
  }')

echo "Policy Response: $POLICY_RESPONSE"

# Extrahiere die Policy ID (sollte elasticsearch-kibana-policy sein)
POLICY_ID=$(echo "$POLICY_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$POLICY_ID" ]; then
  echo "WARNING: Could not extract policy ID, trying to use existing policy"
  POLICY_ID="elasticsearch-kibana-policy"
fi

echo "Agent Policy ID: $POLICY_ID"

# === 2. Füge Elasticsearch Integration zur Policy hinzu ===
echo ""
echo "Adding Elasticsearch integration to policy..."

ES_PACKAGE_RESPONSE=$(curl -s -X POST "http://kibana:5601/api/fleet/package_policies" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d "{
    \"policy_id\": \"${POLICY_ID}\",
    \"package\": {
      \"name\": \"elasticsearch\",
      \"version\": \"1.19.0\"
    },
    \"name\": \"elasticsearch-monitoring\",
    \"description\": \"Collect metrics and logs from Elasticsearch\",
    \"namespace\": \"default\",
    \"inputs\": {
      \"elasticsearch-logfile\": {
        \"enabled\": true,
        \"streams\": {
          \"elasticsearch.audit\": {
            \"enabled\": false
          },
          \"elasticsearch.deprecation\": {
            \"enabled\": false
          },
          \"elasticsearch.gc\": {
            \"enabled\": false
          },
          \"elasticsearch.server\": {
            \"enabled\": true,
            \"vars\": {
              \"paths\": [\"/var/log/elasticsearch/*_server.json\"]
            }
          },
          \"elasticsearch.slowlog\": {
            \"enabled\": false
          }
        }
      },
      \"elasticsearch-elasticsearch/metrics\": {
        \"enabled\": true,
        \"vars\": {
              \"hosts\": [\"http://es01:9200\"],
              \"username\": \"elastic\",
              \"password\": \"${ELASTIC_PASSWORD}\"
            },
        \"streams\": {
          \"elasticsearch.stack_monitoring.ccr\": {
            \"enabled\": false
          },
          \"elasticsearch.stack_monitoring.cluster_stats\": {
            \"enabled\": true
          },
          \"elasticsearch.stack_monitoring.enrich\": {
            \"enabled\": false
          },
          \"elasticsearch.stack_monitoring.index\": {
            \"enabled\": true
          },
          \"elasticsearch.stack_monitoring.index_recovery\": {
            \"enabled\": false
          },
          \"elasticsearch.stack_monitoring.index_summary\": {
            \"enabled\": true
          },
          \"elasticsearch.stack_monitoring.ml_job\": {
            \"enabled\": false
          },
          \"elasticsearch.stack_monitoring.node\": {
            \"enabled\": true
          },
          \"elasticsearch.stack_monitoring.node_stats\": {
            \"enabled\": true
          },
          \"elasticsearch.stack_monitoring.pending_tasks\": {
            \"enabled\": false
          },
          \"elasticsearch.stack_monitoring.shard\": {
            \"enabled\": true
          }
        }
      }
    }
  }")

echo "Elasticsearch Package Response: $ES_PACKAGE_RESPONSE"

# === 3. Füge Kibana Integration zur Policy hinzu ===
echo ""
echo "Adding Kibana integration to policy..."

KIBANA_PACKAGE_RESPONSE=$(curl -s -X POST "http://kibana:5601/api/fleet/package_policies" \
  -u "elastic:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  -H "Content-Type: application/json" \
  -d "{
    \"policy_id\": \"${POLICY_ID}\",
    \"package\": {
      \"name\": \"kibana\",
      \"version\": \"2.8.0\"
    },
    \"name\": \"kibana-monitoring\",
    \"description\": \"Collect metrics and logs from Kibana\",
    \"namespace\": \"default\",
    \"inputs\": {
      \"kibana-logfile\": {
        \"enabled\": true,
        \"streams\": {
          \"kibana.audit\": {
            \"enabled\": false
          },
          \"kibana.log\": {
            \"enabled\": true,
            \"vars\": {
              \"paths\": [\"/var/log/kibana/*.json\"]
            }
          }
        }
      },
      \"kibana-kibana/metrics\": {
        \"enabled\": true,
        \"vars\": {
          \"hosts\": [\"http://kibana:5601\"],
          \"username\": \"elastic\",
          \"password\": \"${ELASTIC_PASSWORD}\"
        },
        \"streams\": {
          \"kibana.stack_monitoring.cluster_actions\": {
            \"enabled\": false
          },
          \"kibana.stack_monitoring.cluster_rules\": {
            \"enabled\": false
          },
          \"kibana.stack_monitoring.node_actions\": {
            \"enabled\": false
          },
          \"kibana.stack_monitoring.node_rules\": {
            \"enabled\": false
          },
          \"kibana.stack_monitoring.stats\": {
            \"enabled\": true
          },
          \"kibana.stack_monitoring.status\": {
            \"enabled\": true
          }
        }
      },
      \"kibana-http/metrics\": {
        \"enabled\": true,
        \"vars\": {
              \"hosts\": [\"http://kibana:5601\"],
              \"username\": \"elastic\",
              \"password\": \"${ELASTIC_PASSWORD}\"
            },
        \"streams\": {
          \"kibana.background_task_utilization\": {
            \"enabled\": true
          },
          \"kibana.task_manager_metrics\": {
            \"enabled\": true
          }
        }
      }
    }
  }")

echo "Kibana Package Response: $KIBANA_PACKAGE_RESPONSE"

echo ""
echo "=== Fleet Agent Policies Setup completed successfully ==="
echo "Policy ID: $POLICY_ID"
echo "Integrations added: Elasticsearch, Kibana"

