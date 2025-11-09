# Logstash Konfiguration

Diese Verzeichnisstruktur enthält die Logstash-Konfiguration für die Schulungsumgebung.

## Struktur

```
logstash/
├── pipelines.yml           # Pipeline-Definitionen
├── conf.d/                 # Pipeline-Konfigurationen
│   └── syslog-pipeline.conf
└── README.md              # Diese Datei
```

## Verwendung

### Docker Compose starten

```bash
docker compose up -d logstash
```

### Logs überwachen

```bash
docker compose logs -f logstash
```

### Pipeline testen

```bash
# Konfiguration testen (ohne Start)
docker compose exec logstash bin/logstash -f /usr/share/logstash/pipeline/syslog-pipeline.conf --config.test_and_exit
```

## Eigene Pipeline erstellen

1. Erstellen Sie eine neue `.conf` Datei in `conf.d/`:
   ```bash
   touch data/configs/logstash/conf.d/my-pipeline.conf
   ```

2. Konfigurieren Sie Input, Filter und Output

3. Optional: Fügen Sie die Pipeline zu `pipelines.yml` hinzu:
   ```yaml
   - pipeline.id: my-pipeline
     path.config: "/usr/share/logstash/pipeline/my-pipeline.conf"
     pipeline.workers: 2
   ```

4. Starten Sie Logstash neu:
   ```bash
   docker compose restart logstash
   ```

## Beispiel: Syslog-Pipeline

Die mitgelieferte `syslog-pipeline.conf` zeigt:

- **Input:** Beats-Input auf Port 5044
- **Filter:** 
  - Grok-Parsing mit `%{SYSLOGBASE}`
  - Date-Filter für Timestamp-Konvertierung
  - Fehlerbehandlung mit Tags
- **Output:** 
  - Erfolgreiche Events → `logstash-syslog-*`
  - Fehlerhafte Events → `logstash-parse-failures-*`

## Umgebungsvariablen

Die folgenden Variablen sind verfügbar:

- `${ELASTICSEARCH_HOSTS}` - Elasticsearch-URL
- `${ELASTICSEARCH_USERNAME}` - Elasticsearch-Benutzer
- `${ELASTICSEARCH_PASSWORD}` - Elasticsearch-Passwort

## Monitoring

Logstash-Monitoring ist unter Port 9600 verfügbar:

```bash
curl http://localhost:9600/_node/stats
```

## Troubleshooting

**Pipeline startet nicht:**
```bash
# Logs prüfen
docker compose logs logstash

# Konfiguration testen
docker compose exec logstash bin/logstash --config.test_and_exit
```

**Keine Daten in Elasticsearch:**
- Prüfen Sie die Elasticsearch-Verbindung
- Prüfen Sie auf Grok-Parse-Failures
- Aktivieren Sie stdout-Output zum Debuggen

**Hohe CPU-Last:**
- Reduzieren Sie `pipeline.workers`
- Optimieren Sie Grok-Patterns
- Erhöhen Sie `pipeline.batch.delay`

## Best Practices

1. **Konfiguration testen** vor dem Deployment
2. **Monitoring aktivieren** in Production
3. **Persistent Queues** für wichtige Daten
4. **Dead Letter Queue** für Fehleranalyse
5. **Tags verwenden** für konditionale Verarbeitung

