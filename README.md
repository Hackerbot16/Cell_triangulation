# Cell-Tower (NMR) Geolocation for GPS-Denied Tracking

Locate an IoT/GSM-modem device when GPS is unavailable, using the **Network Measurement Report (NMR)** the modem already reports: the serving cell plus its neighbouring cells and their signal strengths. The cell IDs are resolved to coordinates through the [Unwired Labs LocationAPI](https://unwiredlabs.com) and plotted on an interactive [Folium](https://python-visualization.github.io/folium/) map.

<!-- TODO: add a screenshot of the live map here: ![Live map](docs/images/live_map.png) -->

## How it works

```
 IoT modem ──HTTP POST/GET (CSV packet)──▶ Flask server ──▶ geolocator
                                                               │ parse serving + neighbour cells
                                                               ▼
                                              Unwired Labs API (MCC/MNC/LAC|TAC/CID/signal)
                                                               │ lat, lon, accuracy (m)
                                                               ▼
                                              Folium map (marker, accuracy circle, trail)
```

1. The modem sends its telemetry packet as a comma-separated string to the server.
2. `geolocator.py` extracts the cell data (MCC, MNC, LAC/TAC, Cell ID/eNB ID, signal) for the serving cell and up to four neighbours.
3. Those towers are sent to Unwired Labs, which returns an estimated position and accuracy radius.
4. The result is drawn on an HTML map.

## Repository layout

```
src/
  lte/            Current pipeline – 4G/LTE, live map with movement trail
    geolocator.py   packet parser, API client, map + session-log generation
    server.py       Flask server (POST body or GET path/query), /live_map.html, /status
  gsm/            2G/GSM pipeline – fixed-offset NMR parsing (packet fields 27–43)
    geolocator.py   most robust GSM parser (skips empty/invalid neighbours)
    server_json.py  accepts JSON  {"packet_data": "..."}  on POST /data   (port 5000)
    server_raw.py   accepts raw POST body or GET path/query              (port 80)
alternatives/
  github_source/  Fetch packets from a GitHub-hosted text file instead of direct HTTP
archive/          Earlier iterations kept for reference (superseded by src/)
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # add your UNWIRED_API_KEY
set -a; source .env; set +a

# LTE pipeline (port 80 needs sudo, or change `port` in server.py)
cd src/lte
sudo -E python server.py
```

Then point the modem at `http://<server-ip>/` and open `http://<server-ip>/live_map.html`.

Test without hardware by saving one captured packet to a file and posting it yourself:

```bash
curl -X POST --data-binary @my_packet.txt http://127.0.0.1/
```

## Packet formats

| Pipeline | Where the cell data sits | Notes |
|----------|--------------------------|-------|
| GSM | CSV fields **27–43**: serving ASU, MCC, MNC, LAC(hex), CellID(hex), then 4 × (CellID, LAC, RSSI) | ASU converted to dBm as `2·ASU − 113` |
| LTE | After the operator field (`IND airtel`): ASU, then MCC, MNC, TAC(hex), eNB(hex), then neighbours (eNB, TAC, RSRP) | Fields are located by pattern, not fixed offsets |

<!-- TODO: add a sanitised example packet for each format under docs/ -->

## Known limitations

- Accuracy depends on Unwired Labs' tower database coverage; typical error is hundreds of metres.
- The LTE parser looks for the literal operator string `IND airtel` and falls back to MCC 404 / MNC 40. Other operators need a small change.
- Position history and packet log are in-memory and reset on restart.
- Flask runs with `debug=True` in these scripts: fine for a demo, not for deployment.

## Hardware / data

<!-- TODO: modem/module model, how the packet is produced, test route and measured accuracy vs GPS -->

## License

<!-- TODO: choose a license (MIT is common for student projects) -->
