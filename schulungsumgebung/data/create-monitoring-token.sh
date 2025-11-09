#!/bin/bash

# Script zur automatischen Erstellung eines Monitoring Enrollment Tokens
# Dieses Script hilft bei der initialen Einrichtung des Monitoring Agents

set -e

echo "================================================"
echo "Fleet Monitoring Token Generator"
echo "================================================"
echo ""

# Farben für Output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Prüfen, ob .env Datei existiert
if [ ! -f .env ]; then
    echo -e "${RED}Fehler: .env Datei nicht gefunden!${NC}"
    echo "Bitte erstellen Sie zuerst eine .env Datei:"
    echo "  cp env.example .env"
    exit 1
fi

# Environment-Variablen laden
source .env

# Prüfen, ob ELASTIC_PASSWORD gesetzt ist
if [ -z "$ELASTIC_PASSWORD" ]; then
    echo -e "${RED}Fehler: ELASTIC_PASSWORD nicht in .env gesetzt!${NC}"
    exit 1
fi

# Prüfen, ob Container laufen
if ! docker-compose -f docker-compose-es.yml ps | grep -q "kibana"; then
    echo -e "${RED}Fehler: Kibana Container läuft nicht!${NC}"
    echo "Bitte starten Sie zuerst den Stack:"
    echo "  docker-compose -f docker-compose-es.yml up -d"
    exit 1
fi

echo "Warte auf Kibana..."
until docker-compose -f docker-compose-es.yml exec -T kibana curl -s --cacert /usr/share/kibana/config/certs/ca/ca.crt https://localhost:5601/api/status | grep -q "available"; do
    echo -n "."
    sleep 2
done
echo -e "\n${GREEN}Kibana ist bereit!${NC}\n"

# Prüfen, ob Fleet Server Policy existiert
echo "Prüfe Fleet Server Policy..."
FLEET_POLICY_EXISTS=$(docker-compose -f docker-compose-es.yml exec -T kibana curl -s \
    --cacert /usr/share/kibana/config/certs/ca/ca.crt \
    -u "elastic:${ELASTIC_PASSWORD}" \
    -H "kbn-xsrf: true" \
    "https://localhost:5601/api/fleet/agent_policies" | grep -c "Fleet Server Policy" || true)

if [ "$FLEET_POLICY_EXISTS" -eq 0 ]; then
    echo -e "${YELLOW}Erstelle Fleet Server Policy...${NC}"
    docker-compose -f docker-compose-es.yml exec -T kibana curl -s -X POST \
        --cacert /usr/share/kibana/config/certs/ca/ca.crt \
        -u "elastic:${ELASTIC_PASSWORD}" \
        -H "Content-Type: application/json" \
        -H "kbn-xsrf: true" \
        "https://localhost:5601/api/fleet/agent_policies?sys_monitoring=true" \
        -d '{
            "name": "Fleet Server Policy",
            "namespace": "default",
            "monitoring_enabled": ["logs", "metrics"],
            "has_fleet_server": true
        }' > /dev/null
    echo -e "${GREEN}Fleet Server Policy erstellt!${NC}"
fi

# Prüfen, ob Monitoring Policy existiert, sonst erstellen
echo "Prüfe Monitoring Policy..."
MONITORING_POLICY=$(docker-compose -f docker-compose-es.yml exec -T kibana curl -s \
    --cacert /usr/share/kibana/config/certs/ca/ca.crt \
    -u "elastic:${ELASTIC_PASSWORD}" \
    -H "kbn-xsrf: true" \
    "https://localhost:5601/api/fleet/agent_policies" | grep -o '"id":"[^"]*","name":"Elastic Stack Monitoring Policy"' | grep -o '"id":"[^"]*"' | cut -d'"' -f4 || true)

if [ -z "$MONITORING_POLICY" ]; then
    echo -e "${YELLOW}Erstelle Monitoring Policy...${NC}"
    MONITORING_POLICY=$(docker-compose -f docker-compose-es.yml exec -T kibana curl -s -X POST \
        --cacert /usr/share/kibana/config/certs/ca/ca.crt \
        -u "elastic:${ELASTIC_PASSWORD}" \
        -H "Content-Type: application/json" \
        -H "kbn-xsrf: true" \
        "https://localhost:5601/api/fleet/agent_policies?sys_monitoring=true" \
        -d '{
            "name": "Elastic Stack Monitoring Policy",
            "namespace": "default",
            "monitoring_enabled": ["logs", "metrics"]
        }' | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo -e "${GREEN}Monitoring Policy erstellt mit ID: ${MONITORING_POLICY}${NC}"
else
    echo -e "${GREEN}Monitoring Policy existiert bereits: ${MONITORING_POLICY}${NC}"
fi

# Enrollment Token erstellen
echo ""
echo "Erstelle Enrollment Token für Monitoring Policy..."
TOKEN_RESPONSE=$(docker-compose -f docker-compose-es.yml exec -T kibana curl -s -X POST \
    --cacert /usr/share/kibana/config/certs/ca/ca.crt \
    -u "elastic:${ELASTIC_PASSWORD}" \
    -H "Content-Type: application/json" \
    -H "kbn-xsrf: true" \
    "https://localhost:5601/api/fleet/enrollment_api_keys" \
    -d "{
        \"policy_id\": \"${MONITORING_POLICY}\",
        \"name\": \"Monitoring Token $(date +%Y-%m-%d_%H:%M:%S)\"
    }")

# Token extrahieren
MONITORING_TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"api_key":"[^"]*"' | cut -d'"' -f4)

if [ -z "$MONITORING_TOKEN" ]; then
    echo -e "${RED}Fehler beim Erstellen des Tokens!${NC}"
    echo "Response: $TOKEN_RESPONSE"
    exit 1
fi

echo -e "${GREEN}Token erfolgreich erstellt!${NC}"
echo ""

# Token in .env Datei schreiben
if grep -q "^MONITORING_ENROLLMENT_TOKEN=" .env; then
    # Existierenden Eintrag aktualisieren
    sed -i.bak "s|^MONITORING_ENROLLMENT_TOKEN=.*|MONITORING_ENROLLMENT_TOKEN=${MONITORING_TOKEN}|" .env
    echo -e "${GREEN}MONITORING_ENROLLMENT_TOKEN in .env aktualisiert${NC}"
else
    # Neuen Eintrag hinzufügen
    echo "MONITORING_ENROLLMENT_TOKEN=${MONITORING_TOKEN}" >> .env
    echo -e "${GREEN}MONITORING_ENROLLMENT_TOKEN zu .env hinzugefügt${NC}"
fi

echo ""
echo "================================================"
echo -e "${GREEN}Setup abgeschlossen!${NC}"
echo "================================================"
echo ""
echo "Ihr Enrollment Token:"
echo -e "${YELLOW}${MONITORING_TOKEN}${NC}"
echo ""
echo "Nächste Schritte:"
echo "1. Starten Sie den Monitoring Agent neu:"
echo -e "   ${YELLOW}docker-compose -f docker-compose-es.yml restart elastic-agent-monitoring${NC}"
echo ""
echo "2. Überprüfen Sie den Status in Kibana:"
echo -e "   ${YELLOW}http://localhost:${KIBANA_PORT:-5601}${NC}"
echo "   → Management → Fleet → Agents"
echo ""
echo "3. Fügen Sie Integrationen zur Policy hinzu:"
echo "   → Fleet → Agent policies → Elastic Stack Monitoring Policy"
echo "   → Add integration → Elasticsearch / Kibana"
echo ""

