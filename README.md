# Elastic Stack Schulungsumgebung

Eine vollständige Elastic-Stack-Umgebung für den eigenen Rechner, gestartet mit einem einzigen Befehl. Sie ist die Arbeitsgrundlage für das [Elastic Stack Training von modellagenten](https://www.modellagenten.de/trainings/elastic-stack-training). Sie eignet sich aber auch für alle, die Elasticsearch, Kibana, Logstash, Beats und Fleet praktisch ausprobieren möchten.

Nach dem Start stehen bereit:

- **Elasticsearch** als Single-Node-Cluster mit aktivierter Security und Trial-Lizenz
- **Kibana** mit vorkonfiguriertem Fleet
- **Filebeat** und **Logstash** für klassische Log-Pipelines
- **Fleet Server** inklusive APM-Endpunkt
- **Elastic Agent**, der Elasticsearch und Kibana per Integration überwacht (Logs und Metriken)
- **Beispieldaten** (Apache, Syslog, JBoss, Java-Stacktraces) und ein optionaler **Log-Generator** für realistische Live-Daten und Störungsszenarien

## Voraussetzungen

- [Docker Desktop](https://docs.docker.com/get-docker/) oder Docker Engine mit Docker Compose v2 (`docker compose version`)
- Mindestens **8 GB RAM** für Docker (Elasticsearch ist standardmäßig auf 8 GB begrenzt, siehe `MEM_LIMIT`)
- Rund 10 GB freier Speicherplatz für Images und Daten
- Freie Ports: `9200`, `5601`, `5044`, `9600`, `8220`, `8200`
- Unter Linux zusätzlich: `sudo sysctl -w vm.max_map_count=262144` ([Hintergrund](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-prod#_set_vm_max_map_count_to_at_least_262144))

## Schnellstart

```bash
# 1. Konfiguration anlegen (falls noch keine .env existiert)
cp env.example .env

# 2. Umgebung starten
docker compose up -d

# 3. Fortschritt verfolgen
docker compose ps -a
```

Der erste Start dauert je nach Internetverbindung 5 bis 10 Minuten, weil alle Images geladen werden. Danach ist die Umgebung in etwa 2 Minuten oben.

Anschließend öffnen Sie Kibana unter [http://localhost:5601](http://localhost:5601) und melden sich mit `elastic` / `elastic1234` an.

## Zugänge

| Dienst | URL | Benutzer | Passwort |
|---|---|---|---|
| Kibana | http://localhost:5601 | `elastic` | `elastic1234` |
| Elasticsearch | http://localhost:9200 | `elastic` | `elastic1234` |
| Fleet Server | http://localhost:8220 | - | - |
| APM Server | http://localhost:8200 | - | - |
| Logstash Beats-Input | localhost:5044 | - | - |
| Logstash Monitoring API | http://localhost:9600 | - | - |

Die Passwörter stammen aus der `.env`. Wenn Sie `KIBANA_PASSWORD` ändern, passen Sie auch `elasticsearch.password` in `configs/kibana/kibana.yml` an.

## Was beim Start passiert

Die Dienste starten in einer festen Reihenfolge. Einmalige Setup-Container erledigen die Konfiguration automatisch und beenden sich danach mit `Exited (0)`. Das ist so gewollt.

1. `setup` setzt das Passwort für den Benutzer `kibana_system`.
2. `es01` (Elasticsearch) und `kibana` starten.
3. `fleet-server-bootstrap` legt die Fleet-Server-Policy an.
4. `fleet-server` registriert sich bei Kibana.
5. `fleet-policy-setup` erstellt die Policy `elasticsearch-kibana` mit den Integrationen für Elasticsearch und Kibana.
6. `fleet-token-fetcher` holt den Enrollment-Token für diese Policy.
7. `elastic-agent-monitoring` registriert sich mit dem Token und sammelt Logs und Metriken von Elasticsearch und Kibana.

Prüfen, ob alles läuft:

```bash
curl -u elastic:elastic1234 "http://localhost:9200/_cluster/health?pretty"
docker compose exec elastic-agent-monitoring elastic-agent status
```

In Kibana sehen Sie unter **Management > Fleet** zwei gesunde Agents, unter **Stack Monitoring** den Cluster und in **Discover** die Data Streams `logs-elasticsearch.server-default` und `logs-kibana.log-default`.

## Verzeichnisstruktur

```
.
├── docker-compose.yml            # Alle Dienste der Umgebung
├── docker-compose.airgapped.yml  # Ergänzung für Betrieb ohne Internet
├── env.example                   # Vorlage für die .env
├── configs/                      # Konfiguration für Elasticsearch, Kibana, Filebeat, Logstash
├── data/                         # Beispieldaten, in Filebeat, Logstash und Agent unter /var/log/data eingebunden
├── fleet-packages/               # Integrationspakete für den Offline-Betrieb
├── generator/                    # Log-Generator (loggen)
└── scripts/                      # Setup-Skripte für Fleet und Demos
```

## Beispieldaten

Alle Dateien aus `data/` sind in Filebeat, Logstash und Elastic Agent unter `/var/log/data` eingebunden (nur lesend). Neue Dateien, die Sie dort ablegen, sind sofort in den Containern sichtbar.

| Datei | Inhalt |
|---|---|
| `apache_logs` | ca. 10.000 Apache Access Logs |
| `syslog-sample.log`, `syslog.1`, `syslog.2` | Linux-Syslog |
| `jboss-standard.log`, `jboss-json.log` | JBoss-Logs, klassisch und als JSON |
| `java_exception.log` | Mehrzeilige Java-Stacktraces |
| `logstash-tutorial-dataset.log` | Datensatz aus dem Logstash-Tutorial |

## Log-Generator für Live-Daten

Für Alerting, Dashboards und ES|QL-Übungen braucht man Daten mit aktuellem Zeitstempel. Der Generator erzeugt kontinuierlich Logs (Apache, Nginx, Syslog, Auth, Firewall, Java) in `data/generated/`. Er startet nur auf Anfrage:

```bash
docker compose --profile generator up -d loggen
```

Störungsszenarien spielen Sie im laufenden Betrieb ein, zum Beispiel:

```bash
docker compose exec loggen python loggen.py scenario --list        # alle Szenarien anzeigen
docker compose exec loggen python loggen.py scenario brute-force   # SSH-Brute-Force simulieren
docker compose exec loggen python loggen.py scenario error-spike --duration 10m
docker compose exec loggen python loggen.py scenario --status
```

Verfügbare Szenarien: `error-spike`, `brute-force`, `latency-degradation`, `host-silent`, `disk-full`, `oom`, `new-user-agent`, `rare-process`.

Profil und Rate steuern Sie über `LOGGEN_PROFILE` (Standard `alerting`) und `LOGGEN_RATE` (Standard `10` Ereignisse pro Sekunde) in der `.env`.

## Betrieb ohne Internet (Air-Gapped)

Kibana lädt Integrationen standardmäßig aus der Elastic Package Registry. In Schulungsräumen mit eingeschränktem Netz verwenden Sie die mitgelieferten Pakete aus `fleet-packages/`:

```bash
docker compose -f docker-compose.yml -f docker-compose.airgapped.yml up -d
```

Die Docker-Images müssen in diesem Fall vorab geladen sein (`docker compose pull`).

## Nützliche Befehle

```bash
docker compose logs -f kibana                   # Logs eines Dienstes verfolgen
docker compose restart logstash                 # Dienst nach Konfigurationsänderung neu starten
docker compose stop                             # Umgebung anhalten, Daten bleiben erhalten
docker compose up -d                            # Umgebung wieder starten
docker compose down -v                          # Alles entfernen, inklusive aller Daten (Neustart bei null)
```

## Fehlerbehebung

**Elasticsearch startet nicht oder beendet sich sofort**
Meist fehlt Arbeitsspeicher. Erhöhen Sie den Speicher in Docker Desktop oder reduzieren Sie `MEM_LIMIT` in der `.env` (zum Beispiel auf `4294967296` für 4 GB). Unter Linux prüfen Sie zusätzlich `vm.max_map_count`.

**Kibana zeigt "Kibana server is not ready yet"**
Kibana braucht nach Elasticsearch noch ein bis zwei Minuten. Prüfen Sie den Status mit `docker compose logs -f kibana`.

**Ein Setup-Container ist mit einem Fehler beendet**
Die Ausgabe zeigt die Ursache, zum Beispiel:

```bash
docker compose logs fleet-server-bootstrap fleet-policy-setup fleet-token-fetcher
```

Erscheint der Hinweis, dass ein Paket nicht abrufbar ist, fehlt der Zugriff auf `epr.elastic.co`. Nutzen Sie dann den [Air-Gapped-Modus](#betrieb-ohne-internet-air-gapped).

**Der Monitoring-Agent registriert sich nicht**
Nach einem `docker compose down` ohne `-v` kann ein veralteter Token oder Agent-Zustand übrig bleiben. Ein sauberer Neustart hilft:

```bash
docker compose down -v
docker compose up -d
```

**Port bereits belegt**
Passen Sie `ES_PORT`, `KIBANA_PORT`, `LOGSTASH_PORT` oder `FLEET_PORT` in der `.env` an.

## Hinweis zur Sicherheit

Diese Umgebung ist für Schulung und lokale Experimente gebaut: feste Passwörter, kein TLS, Single Node, keine Replikas. Für den produktiven Betrieb gelten andere Regeln. Genau darum geht es im Trainingsmodul "Best Practices für Produktion und Skalierung".

## Das Training zur Umgebung

Eine laufende Umgebung ist der erste Schritt. Richtig wertvoll wird sie, wenn Ihr Team weiß, wie man daraus ein verlässliches Logging- und Monitoring-System macht.

Im **[Elastic Stack Training von modellagenten](https://www.modellagenten.de/trainings/elastic-stack-training)** lernen Sie in drei Tagen praxisnah:

- Daten mit **Filebeat, Logstash, Elastic Agent und OpenTelemetry** zuverlässig einzulesen und zu transformieren
- **Fleet** für die zentrale Verwaltung von Agents und Integrationen einzusetzen
- Daten in **Kibana** mit Discover, ES|QL, Lens und Dashboards zu analysieren
- **Alerting**, Stack Monitoring und APM für proaktives Monitoring aufzusetzen
- Cluster **produktionsreif** zu betreiben: Security, Index Lifecycle, Hochverfügbarkeit und Performance

Was das Training auszeichnet:

- **Hands-on statt Folienschlacht:** Jede Einheit endet in einer Übung in genau dieser Umgebung.
- **Ihre Logs, Ihre Fragen:** Als In-House-Schulung passen wir die Inhalte an Ihre Datenquellen an, ob Syslog, Windows Events, Webserver, Datenbanken oder Container.
- **Erfahrung aus der Praxis:** Trainer Uli Zellbeck ist zertifizierter Elastic Engineer und baut seit über 10 Jahren Such-, Logging- und Monitoring-Lösungen mit Elasticsearch auf.
- **Flexibel:** vor Ort in Köln, bei Ihnen im Haus oder remote, für Einsteiger und Fortgeschrittene.

Termine für offene Schulungen und Konditionen für In-House-Trainings finden Sie auf der [Trainingsseite](https://www.modellagenten.de/trainings/elastic-stack-training). Für ein individuelles Angebot schreiben Sie an [training@modellagenten.de](mailto:info@modellagenten.de).

Sie arbeiten vor allem mit Dashboards und Visualisierungen? Dann passt die [Kibana-Schulung](https://www.modellagenten.de/trainings/kibana-training). Für Architektur- und Betriebsfragen gibt es die [Elasticsearch-Beratung](https://www.modellagenten.de/services/elasticsearch-beratung).
