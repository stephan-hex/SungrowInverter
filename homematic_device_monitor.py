pipimport requests
import json
import os

class HomematicStatusChecker:
    """
    Klasse zur gezielten Abfrage von Homematic-Datenpunkten basierend auf einer JSON-Konfiguration.
    """
    def __init__(self, ip, user, password):
        self.url = f"http://{ip}:8181/tclrega.exe"
        self.session = requests.Session()
        self.session.auth = (user, password)
        self.last_error = None

    def _execute_rega_script(self, script):
        """Sendet das Skript an die CCU und gibt den Textinhalt zurück."""
        self.last_error = None
        try:
            response = self.session.post(self.url, data=script, timeout=10)
            response.raise_for_status()
            # CCU Antwort parsen (Inhalt vor dem XML-Block)
            return response.text.split("<xml>")[0].strip()
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                error_msg = f"HTTP {e.response.status_code} ({e.response.reason})"
            self.last_error = error_msg
            print(f"Kommunikationsfehler mit der CCU: {error_msg}")
            return None

    def _convert_type(self, value_str, target_type):
        """Konvertiert den String-Wert der CCU in den gewünschten Python-Datentyp."""
        if value_str is None or value_str.lower() == "null" or value_str == "":
            return None
        
        try:
            if target_type == "bool":
                return value_str.lower() == "true"
            elif target_type == "float":
                return float(value_str)
            elif target_type == "int":
                # Erst zu float, dann zu int, um Strings wie "1.0" sicher zu wandeln
                return int(float(value_str))
            return value_str
        except (ValueError, TypeError):
            return value_str

    def fetch_status(self, config_file):
        """Fragt alle Statuswerte außer LOW_BAT ab."""
        # Filtert alles aus, was "LOW_BAT" oder "LOWBAT" im Namen hat
        return self._fetch_filtered_data(config_file, lambda name: "LOW_BAT" not in name.upper() and "LOWBAT" not in name.upper(), "Aktuelle Messwerte & Status")

    def check_low_bat(self, config_file):
        """Fragt gezielt nur die LOW_BAT Datenpunkte ab."""
        # Nimmt nur Datenpunkte auf, die "LOW_BAT" oder "LOWBAT" im Namen haben
        return self._fetch_filtered_data(config_file, lambda name: "LOW_BAT" in name.upper() or "LOWBAT" in name.upper(), "Batteriestatus (LOW_BAT)")

    def _fetch_filtered_data(self, config_file, name_filter, label):
        """Interne Methode zum Abrufen gefilterter Datenpunkte."""
        if not os.path.exists(config_file):
            print(f"Fehler: Konfigurationsdatei {config_file} nicht gefunden.")
            return []

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        tasks = []
        rega_script = "object o;"
        
        # HMScript dynamisch aufbauen
        for device in config.get("devices", []):
            addr = device.get("address")
            interface = device.get("interface", "HmIP-RF")
            
            for dp in device.get("datapoints", []):
                chan = dp.get("channel")
                dp_name = dp.get("name")
                
                # Hier hat die Prüfung gefehlt:
                if not name_filter(dp_name):
                    continue
                
                target = f"{interface}.{addr}:{chan}.{dp_name}"
                
                tasks.append({
                    "device_name": device.get("name"),
                    "target": target,
                    "type": dp.get("type")
                })
                # Jeweils eine Zeile Output pro Datenpunkt generieren
                rega_script += f'\no = dom.GetObject("{target}"); if(o){{WriteLine(o.Value());}}else{{WriteLine("null");}}'

        if not tasks:
            print(f"Keine Datenpunkte für '{label}' in der Konfiguration gefunden.")
            return []

        raw_output = self._execute_rega_script(rega_script)
        if raw_output is None:
            return []

        results = []
        lines = raw_output.splitlines()
        
        # Konsolenausgabe Header
        print(f"\n--- {label} ---")
        print(f"{'Gerät':<20} | {'Datenpunkt':<40} | {'Wert':<12} | {'Typ'}")
        print("-" * 90)

        for i, task in enumerate(tasks):
            val_str = lines[i] if i < len(lines) else "null"
            converted_value = self._convert_type(val_str, task["type"])
            
            results.append({
                "device": task["device_name"],
                "datapoint": task["target"],
                "value": converted_value
            })
            
            print(f"{task['device_name']:<20} | {task['target']:<40} | {str(converted_value):<12} | {type(converted_value).__name__}")
            
        return results

if __name__ == "__main__":
    # Ermittelt den Pfad relativ zum Standort dieses Skripts
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    with open(os.path.join(BASE_DIR, "CCU_credentials.json"), "r") as f:
        creds = json.load(f)

    checker = HomematicStatusChecker(creds["ccu_ip"], creds["user"], creds["password"])
    CONFIG = os.path.join(BASE_DIR, "homematic_device_config.json")

    # --- ABFRAGE 1: MESSWERTE ---
    print("\nSTARTE ABFRAGE: Messwerte...")
    checker.fetch_status(CONFIG)

    # --- ABFRAGE 2: BATTERIE ---
    # print("\nSTARTE ABFRAGE: Batterietest...")
    # checker.check_low_bat(CONFIG)
    