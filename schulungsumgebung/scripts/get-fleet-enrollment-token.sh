#!/bin/sh
set -e

echo "=== Fleet Enrollment Token Fetcher ==="
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
echo "Fetching enrollment tokens from Fleet API..."

# Rufe alle Enrollment API Keys ab
RESPONSE=$(curl -s -u "elastic:${ELASTIC_PASSWORD}" \
  -H "kbn-xsrf: true" \
  "http://kibana:5601/api/fleet/enrollment_api_keys")

echo "API Response received"

# Versuche den Token für die elasticsearch-kibana-policy zu finden
# Suche nach einem aktiven Token für diese spezifische Policy
POLICY_ID="elasticsearch-kibana-policy"

# Extrahiere alle Items und filtere nach policy_id
# Da wir kein jq haben, verwenden wir grep und sed für einfaches Parsing
ENROLLMENT_TOKEN=$(echo "$RESPONSE" | tr '}' '\n' | grep "\"policy_id\":\"${POLICY_ID}\"" | grep '"active":true' | grep -o '"api_key":"[^"]*"' | head -1 | cut -d'"' -f4)

if [ -z "$ENROLLMENT_TOKEN" ]; then
  echo "No active token found for policy '${POLICY_ID}', creating a new one..."
  
  # Erstelle einen neuen Enrollment Token für die elasticsearch-kibana-policy
  CREATE_RESPONSE=$(curl -s -u "elastic:${ELASTIC_PASSWORD}" \
    -X POST \
    -H "kbn-xsrf: true" \
    -H "Content-Type: application/json" \
    "http://kibana:5601/api/fleet/enrollment_api_keys" \
    -d "{
      \"name\": \"Monitoring Agent Token - $(date +%Y%m%d_%H%M%S)\",
      \"policy_id\": \"${POLICY_ID}\"
    }")
  
  ENROLLMENT_TOKEN=$(echo "$CREATE_RESPONSE" | grep -o '"api_key":"[^"]*"' | cut -d'"' -f4)
  
  if [ -z "$ENROLLMENT_TOKEN" ]; then
    echo "ERROR: Failed to create enrollment token"
    echo "Response: $CREATE_RESPONSE"
    exit 1
  fi
  
  echo "New enrollment token created successfully for policy '${POLICY_ID}'"
else
  echo "Found existing active token for policy '${POLICY_ID}'"
fi

# Speichere den Token in eine Datei
echo "$ENROLLMENT_TOKEN" > /tmp/fleet-enrollment-token

echo "Enrollment token saved to /tmp/fleet-enrollment-token"
echo "Token: ${ENROLLMENT_TOKEN:0:20}..."
echo "=== Token fetch completed successfully ==="

