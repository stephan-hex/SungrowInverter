import time
import json
import urllib.request
import urllib.error

# --- Konfiguration ---
#PV_API_URL      = "http://localhost:8080/api"
PV_API_URL      = "http://192.168.178.58:8080/api"

GOE_IP          = "192.168.178.142"  # <-- HIER BITTE DIE IP DES CHARGERS EINTRAGEN

SOC_START       = 47.0      # Ladevorgang STARTEN, wenn Akku > 50%
SOC_STOP        = 46.0      # Ladevorgang STOPPEN, wenn Akku < 45% (Hysterese)
CHARGING_AMPS   = 6         # Ladestrom in Ampere (Konstant)
CHECK_INTERVAL  = 60        # Alle 60 Sekunden prüfen

def get_pv_soc():
    """Holt den aktuellen SOC von der lokalen PV-API."""
    try:
        with urllib.request.urlopen(PV_API_URL, timeout=5) as url:
            data = json.loads(url.read().decode())
            
            # Der Wert kommt als String z.B. "55.0 %" oder "55.0"
            soc_str = data.get("battery_soc", "0")
            
            # Einheit entfernen (falls vorhanden) und zu Float konvertieren
            # split()[0] nimmt den ersten Teil des Strings ("55.0" von "55.0 %")
            soc_val = float(str(soc_str).split()[0])
            return soc_val
    except Exception as e:
        print(f"WARNUNG: Fehler beim Abrufen der PV-Daten: {e}")
        return None

def get_goe_status():
    """Holt den aktuellen Status vom Go-eCharger."""
    try:
        url = f"http://{GOE_IP}/api/status"
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"FEHLER beim Abrufen des Go-e Status: {e}")
        return None

def translate_car_status(status_code):
    """Übersetzt den 'car' Statuscode in einen lesbaren Text."""
    status_map = {
        "1": "Angeschlossen, lädt nicht",
        "2": "LÄDT GERADE",
        "3": "Wartet auf Fahrzeug",
        "4": "Laden beendet"
    }
    return status_map.get(str(status_code), f"Unbekannt ({status_code})")

def set_goe_charging(enable, amps=6):
    """Sendet den Steuerbefehl an den Go-eCharger."""
    try:
        # API V2: /api/set?frc=X&amp=Y
        # frc=1 -> Nicht laden erzwingen
        # frc=2 -> Laden erzwingen
        frc_val = "2" if enable else "1"
        url = f"http://{GOE_IP}/api/set?frc={frc_val}"
        if enable:
            url += f"&amp={amps}"
        
        print(f" -> Sende an Go-e (V2): frc={frc_val}, amp={amps if enable else '-'}")
        with urllib.request.urlopen(url, timeout=5) as resp:
            resp.read()

        print("    Erfolgreich gesendet.")
        return True
            
    except Exception as e:
        print(f"FEHLER beim Steuern des Go-e Chargers: {e}")
        return False

def main():
    print("--- Go-e Charger PV-Control gestartet ---")
    print(f"PV API:  {PV_API_URL}")
    print(f"Go-e IP: {GOE_IP}")
    print(f"Regel:   Start > {SOC_START}% | Stop < {SOC_STOP}%")
    print(f"Strom:   {CHARGING_AMPS} A")
    print("-------------------------------------------")

    # Wir merken uns den Zustand nicht persistent, sondern senden bei Grenzwertüberschreitung.
    # Um unnötigen Traffic zu vermeiden, könnte man hier den aktuellen Status vom Go-e abfragen.
    # Hier: Einfache Logik basierend auf den Schwellwerten.
    
    while True:
        soc = get_pv_soc()
        goe_status = get_goe_status()
        
        # Status-Zeile für die Ausgabe vorbereiten
        status_line = ""
        if goe_status:
            car_status_code = goe_status.get('car')
            car_status_text = translate_car_status(car_status_code)
            
            # 'eto' ist die geladene Energie in 0.1 kWh
            charged_energy_kwh = goe_status.get('eto', 0) / 10.0
            
            status_line = f" | Go-e: {car_status_text}, Geladen: {charged_energy_kwh:.2f} kWh"
        
        if soc is not None:
            timestamp = time.strftime("%H:%M:%S")
            if soc > SOC_START:
                print(f"[{timestamp}] SOC {soc:.1f}% > {SOC_START}% -> LADEFREIGABE{status_line}")
                set_goe_charging(True, CHARGING_AMPS)
            elif soc < SOC_STOP:
                print(f"[{timestamp}] SOC {soc:.1f}% < {SOC_STOP}% -> LADE-STOPP{status_line}")
                set_goe_charging(False)
            else:
                print(f"[{timestamp}] SOC {soc:.1f}% (Hysterese {SOC_STOP}-{SOC_START}%){status_line} -> Keine Aktion")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()