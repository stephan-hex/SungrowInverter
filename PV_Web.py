import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import time
import json
import socket

class PV_Web:
    def __init__(self, fetch_data_callback, port=8080):
        self.fetch_data_callback = fetch_data_callback
        self.port = port
        self.template_path = os.path.join(os.path.dirname(__file__), 'index.html')

    def start(self):
        handler_class = self._create_handler()
        # Erlaubt den sofortigen Neustart des Ports
        HTTPServer.allow_reuse_address = True
        server = HTTPServer(('0.0.0.0', self.port), handler_class)
        
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
                    
                    try:
                        # Wert parsen (z.B. "-500 W" -> -500.0)
                        val = float(batt_power_str.split()[0])
                        if val < -10:
                            flow_text = f"🔋 Batterie wird geladen ({batt_power_str}) ⬅️"
                            flow_color = "#2ecc71" # Grün
                        elif val > 50:
                            flow_text = f"⚡ Batterie wird entladen ({batt_power_str}) ➡️"
                            flow_color = "#e67e22" # Orange
                        else:
                            flow_text = f"💤 Batterie Standby ({batt_power_str}) ⏸️"
                            flow_color = "gray"
                    except (ValueError, IndexError):
                        pass

                    # Daten für Template vorbereiten
                    replacements = data.copy()
                    replacements['flow_text'] = flow_text
                    replacements['flow_color'] = flow_color
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