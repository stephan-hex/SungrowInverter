# Requires a joson file with the ESP32 Config
#ESP32_Sensor_config.json
#{
#    "ip_address": "192.168.178.163",
#    "water_level_min": 80,
#    "water_level_max": 160
#}

import json
import os
import time
import urllib.request
from urllib.error import URLError

class ESP32SensorReader:
    POLL_INTERVAL = 60  # Zykluszeit in Sekunden

    def __init__(self):
        self.config_path = os.path.join(os.path.dirname(__file__), "ESP32_Sensor_config.json")
        self.ip_address = "unknown"
        self.min_dist = 80
        self.max_dist = 160
        
        # Letzte gültige Werte
        self.last_temp = None
        self.last_dist = None
        self.last_percent = None
        
        self._load_config()

    def _load_config(self):
        """Lädt die Konfiguration oder erstellt ein Default-Template."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    cfg = json.load(f)
                    self.ip_address = cfg.get("ip_address", "192.168.178.100")
                    self.min_dist = cfg.get("water_level_min", 80)
                    self.max_dist = cfg.get("water_level_max", 160)
            except Exception as e:
                print(f"Fehler beim Laden der ESP32 Config: {e}")
        else:
            # Erstelle ein neues JSON File als Template
            default_cfg = {
                "ip_address": "192.168.178.100",
                "water_level_min": 80,
                "water_level_max": 160
            }
            try:
                with open(self.config_path, "w") as f:
                    json.dump(default_cfg, f, indent=4)
                print(f"\n[HINWEIS] Konfigurationsdatei '{os.path.basename(self.config_path)}' wurde nicht gefunden.")
                print(f"Ein Template wurde unter {self.config_path} erstellt.")
                print("BITTE EDITIEREN SIE DIE DATEI (IP-Adresse/Pegel) UND STARTEN SIE DAS SKRIPT NEU.\n")
            except Exception as e:
                print(f"Fehler beim Erstellen des Config-Templates: {e}")

    def _calculate_percentage(self, distance):
        """
        Berechnet den Füllstand in %.
        Voll (100%): distance <= water_level_min
        Leer (0%):   distance >= water_level_max
        """
        if distance <= self.min_dist:
            return 100.0
        if distance >= self.max_dist:
            return 0.0
        
        # Lineare Skalierung: 100% bei Min, 0% bei Max
        range_total = self.max_dist - self.min_dist
        distance_offset = distance - self.min_dist
        percent = 100.0 - (distance_offset / range_total * 100.0)
        return round(percent, 1)

    def fetch_data(self):
        """Holt die Daten vom ESP32 über die HTTP API."""
        url = f"http://{self.ip_address}/"
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                # Daten extrahieren laut deinem Format
                self.last_temp = data["temperature"]["celsius"]
                self.last_dist = data["ultrasonic"]["distance_cm"]
                self.last_percent = self._calculate_percentage(self.last_dist)
                
                print(f"[{time.strftime('%H:%M:%S')}] ESP32 Daten empfangen:")
                print(f"  Temperatur: {self.last_temp}°C")
                print(f"  Abstand:    {self.last_dist} cm")
                print(f"  Füllstand:  {self.last_percent}%")
                
                return True
        except (URLError, KeyError, json.JSONDecodeError) as e:
            print(f"[{time.strftime('%H:%M:%S')}] Fehler beim Abrufen der ESP-Daten: {e}")
            if self.last_percent is not None:
                print(f"  -> Zeige letzten gültigen Wert: {self.last_percent}% (Temp: {self.last_temp}°C)")
            return False

if __name__ == "__main__":
    # Einfacher Funktionstest bei direktem Aufruf
    reader = ESP32SensorReader()
    reader.fetch_data()