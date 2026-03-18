import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os
import time
import json
import socket
import sqlite3
import datetime

class PV_Web:
    def __init__(self, fetch_data_callback, port=8080):
        self.fetch_data_callback = fetch_data_callback
        self.port = port
        self.template_path = os.path.join(os.path.dirname(__file__), 'index.html')

    def start(self):
        handler_class = self._create_handler()
        # Erlaubt den sofortigen Neustart des Ports
        ThreadingHTTPServer.allow_reuse_address = True
        server = ThreadingHTTPServer(('0.0.0.0', self.port), handler_class)
        
        # Eigene IP-Adresse im Netzwerk ermitteln (für die Anzeige)
        host_ip = "localhost"
        try:
            # Dummy-Verbindung aufbauen (sendet keine Daten), um die lokale IP zu finden
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(("8.8.8.8", 80))
            host_ip = s.getsockname()[0]
            s.close()
        except Exception:
            pass

        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        print(f"Webserver läuft. Erreichbar unter:\n  Lokal:    http://localhost:{self.port}\n  Netzwerk: http://{host_ip}:{self.port}")

    def _create_handler(self):
        pv_web_instance = self
        
        class PVHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/api':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()

                    data = pv_web_instance.fetch_data_callback()
                    self.wfile.write(json.dumps(data).encode('utf-8'))

                elif self.path == '/api/live':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()

                    data = pv_web_instance.fetch_data_callback()
                    keys = ['total_dc_power', 'internal_temperature', 'battery_power', 'meter_active_power']
                    result = {k: data.get(k) for k in keys}
                    self.wfile.write(json.dumps(result).encode('utf-8'))

                elif self.path == '/api/history':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.end_headers()

                    db_path = os.path.join(os.path.dirname(__file__), 'pv_data.db')
                    result = {"labels": [], "values": []}
                    try:
                        today = datetime.date.today()
                        start = int(datetime.datetime(today.year, today.month, today.day, 5, 0).timestamp())
                        end   = int(datetime.datetime(today.year, today.month, today.day, 22, 0).timestamp())
                        interval = 120  # Sekunden zwischen zwei Punkten
                        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                        rows = conn.execute(
                            "SELECT timestamp, total_dc_power FROM readings "
                            "WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
                            (start, end)
                        ).fetchall()
                        conn.close()
                        last_ts = None
                        for ts, val in rows:
                            if last_ts is None or (ts - last_ts) >= interval:
                                result["labels"].append(
                                    datetime.datetime.fromtimestamp(ts).strftime("%H:%M")
                                )
                                result["values"].append(
                                    round(val, 1) if val is not None else None
                                )
                                last_ts = ts
                    except Exception as e:
                        result["error"] = str(e)

                    self.wfile.write(json.dumps(result).encode('utf-8'))

                elif self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    
                    # Aktuelle Daten holen
                    data = pv_web_instance.fetch_data_callback()
                    
                    # Template laden
                    content = ""
                    try:
                        if os.path.exists(pv_web_instance.template_path):
                            with open(pv_web_instance.template_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                        else:
                            content = "<h1>Fehler: index.html nicht gefunden</h1>"
                    except Exception as e:
                        content = f"<h1>Fehler beim Lesen der Datei: {e}</h1>"

                    # Zusatzdaten für Flow-Visualisierung berechnen (analog zur UI)
                    batt_power_str = data.get("battery_power", "0 W")
                    flow_text = "Status unbekannt"
                    flow_color = "gray"
                    flow_state = "standby"
                    
                    try:
                        # Wert parsen (z.B. "-500 W" -> -500.0)
                        val = float(batt_power_str.split()[0])
                        if val < -10:
                            flow_text = f"🔋 Batterie wird geladen ({batt_power_str}) ⬅️"
                            flow_color = "#2ecc71" # Grün
                            flow_state = "charging"
                        elif val > 50:
                            flow_text = f"⚡ Batterie wird entladen ({batt_power_str}) ➡️"
                            flow_color = "#e67e22" # Orange
                            flow_state = "discharging"
                        else:
                            flow_text = f"💤 Batterie Standby ({batt_power_str}) ⏸️"
                            flow_color = "gray"
                            flow_state = "standby"
                    except (ValueError, IndexError):
                        pass

                    # Daten für Template vorbereiten
                    replacements = data.copy()
                    replacements['flow_text'] = flow_text
                    replacements['flow_color'] = flow_color
                    replacements['flow_state'] = flow_state
                    replacements['timestamp'] = time.strftime("%H:%M:%S")
                    
                    # Platzhalter im HTML ersetzen
                    for key, val in replacements.items():
                        content = content.replace(f"{{{key}}}", str(val))
                    
                    self.wfile.write(content.encode('utf-8'))
                else:
                    self.send_error(404)
            
            def log_message(self, format, *args):
                pass # Kein Logging in der Konsole, um Output sauber zu halten
                
        return PVHandler