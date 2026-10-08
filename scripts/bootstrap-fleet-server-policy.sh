#!/bin/sh
set -e

KIBANA="http://kibana:5601"
AUTH="elastic:${ELASTIC_PASSWORD}"
POLICY_ID="fleet-server-policy"

kbn() {
  curl -s -u "$AUTH" -H "kbn-xsrf: true" -H "Content-Type: application/json" "$@"
}

echo "=== Fleet Server Policy Bootstrap ==="

# Fleet-Setup anstoßen, damit Preconfiguration aus kibana.yml angewendet wird
kbn -X POST "${KIBANA}/api/fleet/setup" > /dev/null || true

# === 1. fleet_server-Paket installieren (falls nötig) ===
PKG=$(kbn "${KIBANA}/api/fleet/epm/packages/fleet_server")
PKG_STATUS=$(echo "$PKG" | jq -r '.item.status // empty')
PKG_VERSION=$(echo "$PKG" | jq -r '.item.version // empty')

if [ -z "$PKG_VERSION" ]; then
  echo "ERROR: Paket fleet_server nicht abrufbar. Antwort von Kibana:"
  echo "$PKG"
  echo "Hinweis: Ohne Zugriff auf https://epr.elastic.co mit den mitgelieferten Paketen starten:"
  echo "docker compose -f docker-compose.yml -f docker-compose.airgapped.yml up -d"
  exit 1
fi

if [ "$PKG_STATUS" != "installed" ]; then
  echo "Installing fleet_server ${PKG_VERSION}..."
  RESULT=$(kbn -X POST "${KIBANA}/api/fleet/epm/packages/fleet_server/${PKG_VERSION}")
  if echo "$RESULT" | jq -e '.statusCode // empty' > /dev/null; then
    echo "ERROR: Installation fehlgeschlagen: $RESULT"
    exit 1
  fi
fi
echo "fleet_server ${PKG_VERSION} installed"

# === 2. Fleet Server Policy anlegen (falls nicht vorhanden) ===
POLICY=$(kbn "${KIBANA}/api/fleet/agent_policies/${POLICY_ID}")

if ! echo "$POLICY" | jq -e '.item.id' > /dev/null; then
  echo "Creating agent policy ${POLICY_ID}..."
  kbn -X POST "${KIBANA}/api/fleet/agent_policies" -d "{
    \"id\": \"${POLICY_ID}\",
    \"name\": \"Fleet-Server-Policy\",
    \"namespace\": \"default\",
    \"has_fleet_server\": true
  }" > /dev/null
  POLICY=$(kbn "${KIBANA}/api/fleet/agent_policies/${POLICY_ID}")
fi

# === 3. fleet_server-Integration zur Policy hinzufügen (falls nicht vorhanden) ===
HAS_INTEGRATION=$(echo "$POLICY" | jq -r '[.item.package_policies[]? | select(.package.name == "fleet_server")] | length')

if [ "$HAS_INTEGRATION" = "0" ]; then
  echo "Adding fleet_server integration to ${POLICY_ID}..."
  RESULT=$(kbn -X POST "${KIBANA}/api/fleet/package_policies" -d "{
    \"id\": \"fleet_server-1\",
    \"name\": \"fleet_server-1\",
    \"namespace\": \"default\",
    \"policy_ids\": [\"${POLICY_ID}\"],
    \"package\": { \"name\": \"fleet_server\", \"version\": \"${PKG_VERSION}\" },
    \"inputs\": { \"fleet_server-fleet-server\": { \"enabled\": true } },
    \"force\": true
  }")
  if ! echo "$RESULT" | jq -e '.item.id' > /dev/null; then
    echo "ERROR: Integration konnte nicht hinzugefügt werden: $RESULT"
    exit 1
  fi
fi

echo "=== ${POLICY_ID} enthält die fleet_server-Integration ==="
