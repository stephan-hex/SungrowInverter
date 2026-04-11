import threading
import urllib.request
import urllib.parse
from urllib.error import URLError
import json
import hashlib
import os
import time
import xml.etree.ElementTree as ET

# --- PV-Monitor Konfiguration ---
API_URL             = "http://localhost:8080/api"
#API_URL             = "http://192.168.178.58:8080/api"

READ_INTERVAL_S     = 60   # Lesezyklus in Sekunden
WATCHDOG_INTERVAL_S = 300  # Zustandsüberprüfung alle 5 Minuten
LOG_MAX_BYTES       = 100 * 1024  # 100 kByte

# --- Fritz!Box Konfiguration aus JSON laden ---
_config_path = os.path.join(os.path.dirname(__file__), "fritz_config.json")
with open(_config_path, "r", encoding="utf-8") as _f:
    _fritz_cfg = json.load(_f)

FRITZ_IP           = _fritz_cfg["fritz_ip"]
FRITZ_USER         = _fritz_cfg["fritz_user"]
FRITZ_PASSWORD     = _fritz_cfg["fritz_password"]
FRITZ_AIN          = _fritz_cfg["fritz_ain_pv_luefter"]
TEMP_ON_THRESHOLD  = float(_fritz_cfg["temp_on_threshold"])
TEMP_OFF_THRESHOLD = float(_fritz_cfg["temp_off_threshold"])

LOG_PATH = os.path.join(os.path.dirname(__file__), "temp_monitor_error.log")

# --- Interner Zustand ---
_stop_event = threading.Event()
_plug_state = None   # True = ein, False = aus, None = unbekannt
_fritz_sid  = None   # Aktuelle Session-ID


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log_error(soll: str, ist: str, detail: str = ""):
    """Schreibt einen Fehlereintrag in temp_monitor_error.log. Begrenzt die Dateigrösse auf LOG_MAX_BYTES."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] SOLL={soll} IST={ist}"
    if detail:
        line += f" DETAIL={detail}"
    line += "\n"

    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) >= LOG_MAX_BYTES:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        lines = lines[len(lines) // 2:]
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"[ERROR LOG] {line.strip()}")


# ---------------------------------------------------------------------------
# Fritz!Box AHA API
# ---------------------------------------------------------------------------

def _fritz_get_sid():
    base = f"http://{FRITZ_IP}/login_sid.lua"
    # Challenge für Login holen
    with urllib.request.urlopen(base, timeout=10) as r:
        root = ET.fromstring(r.read())
    challenge = root.findtext("Challenge")
    response_str = f"{challenge}-{FRITZ_PASSWORD}"
    md5 = hashlib.md5(response_str.encode("utf-16-le")).hexdigest()
    params = urllib.parse.urlencode({"username": FRITZ_USER, "response": f"{challenge}-{md5}"})
    with urllib.request.urlopen(f"{base}?{params}", timeout=10) as r:
        root = ET.fromstring(r.read())
    sid = root.findtext("SID")
    if not sid or sid == "0000000000000000":
        raise RuntimeError("Fritz!Box Login fehlgeschlagen - Passwort pruefen.")
    print(f"[Fritz] Neue Session ID erstellt: {sid[:4]}...")
    return sid


def _fritz_get_state() -> str:
    """Gibt '1', '0', 'inval' oder leeren String zurück."""
    global _fritz_sid
    try:
        if not _fritz_sid:
            _fritz_sid = _fritz_get_sid()
        params = urllib.parse.urlencode({"ain": FRITZ_AIN, "switchcmd": "getswitchstate", "sid": _fritz_sid})
        with urllib.request.urlopen(f"http://{FRITZ_IP}/webservices/homeautoswitch.lua?{params}", timeout=10) as r:
            return r.read().decode("utf-8").strip()
    except Exception as e:
        print(f"FEHLER Fritz!Box get_state: {e}")
        _fritz_sid = None
        return "inval"


def _fritz_is_present() -> bool:
    """Prüft ob die DECT-Steckdose erreichbar/registriert ist (getswitchpresent)."""
    global _fritz_sid
    try:
        if not _fritz_sid:
            _fritz_sid = _fritz_get_sid()
        params = urllib.parse.urlencode({"ain": FRITZ_AIN, "switchcmd": "getswitchpresent", "sid": _fritz_sid})
        with urllib.request.urlopen(f"http://{FRITZ_IP}/webservices/homeautoswitch.lua?{params}", timeout=10) as r:
            return r.read().decode("utf-8").strip() == "1"
    except Exception as e:
        print(f"FEHLER Fritz!Box is_present: {e}")
        _fritz_sid = None
        return False


def _fritz_switch(on: bool) -> bool:
    global _fritz_sid
    try:
        if not _fritz_sid:
            _fritz_sid = _fritz_get_sid()
        cmd = "setswitchon" if on else "setswitchoff"
        params = urllib.parse.urlencode({"ain": FRITZ_AIN, "switchcmd": cmd, "sid": _fritz_sid})
        with urllib.request.urlopen(f"http://{FRITZ_IP}/webservices/homeautoswitch.lua?{params}", timeout=10) as r:
            r.read()
        actual = _fritz_get_state()
        actual_str = "EIN" if actual == "1" else "AUS" if actual == "0" else actual
        print(f"  -> Steckdose tatsaechlicher Zustand: {actual_str}")
        return True
    except Exception as e:
        print(f"FEHLER Fritz!Box: {e}")
        _fritz_sid = None
        return False


# ---------------------------------------------------------------------------
# Watchdog
# ---------------------------------------------------------------------------

def _watchdog():
    global _plug_state, _fritz_sid
    if _plug_state is None:
        return
    soll_bool = _plug_state
    soll_str  = "EIN" if soll_bool else "AUS"
    try:
        # 1. Erreichbarkeit prüfen
        if not _fritz_is_present():
            _log_error(soll=soll_str, ist="nicht erreichbar", detail="getswitchpresent=0 – Steckdose fehlt oder ausser Reichweite")
            return

        # 2. Zustand prüfen
        actual_raw = _fritz_get_state()
        if actual_raw not in ("0", "1"):
            _log_error(soll=soll_str, ist="unbekannt", detail=f"Ungueltige Zustandsantwort: '{actual_raw}'")
            return

        ist_bool = actual_raw == "1"
        ist_str  = "EIN" if ist_bool else "AUS"
        if ist_bool != soll_bool:
            print(f"[Watchdog] Abweichung: SOLL={soll_str} IST={ist_str} - Korrekturversuch ...")
            success = _fritz_switch(on=soll_bool)
            if not success:
                _log_error(soll=soll_str, ist=ist_str, detail="Korrekturversuch fehlgeschlagen")
    except Exception as e:
        _log_error(soll=soll_str, ist="unbekannt", detail=str(e))
        _fritz_sid = None


# ---------------------------------------------------------------------------
# Monitoring Loop
# ---------------------------------------------------------------------------

def _read_and_control():
    global _plug_state
    raw = ""
    try:
        with urllib.request.urlopen(API_URL, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        raw  = data.get("internal_temperature", "")
        temp = float(str(raw).split()[0])

        if temp >= TEMP_ON_THRESHOLD and _plug_state is not True:
            print(f"{time.strftime('%H:%M:%S')} Temperatur {raw} >= {TEMP_ON_THRESHOLD} C -> Steckdose EIN")
            _fritz_switch(on=True)
            _plug_state = True
        elif temp < TEMP_OFF_THRESHOLD and _plug_state is not False:
            print(f"{time.strftime('%H:%M:%S')} Temperatur {raw} < {TEMP_OFF_THRESHOLD} C -> Steckdose AUS")
            _fritz_switch(on=False)
            _plug_state = False
    except (ValueError, IndexError):
        print(f"FEHLER: Ungueltiger Temperaturwert: {raw!r}")
    except URLError:
        print(f"WARNUNG: Verbindung zu {API_URL} fehlgeschlagen. Läuft 'main_raspi.py'?")
    except Exception as e:
        print(f"FEHLER beim Abrufen der Daten: {e}")


def _loop():
    last_watchdog = time.monotonic()
    while not _stop_event.wait(timeout=READ_INTERVAL_S):
        _read_and_control()
        if time.monotonic() - last_watchdog >= WATCHDOG_INTERVAL_S:
            _watchdog()
            last_watchdog = time.monotonic()


if __name__ == "__main__":
    print(f"Temperatur-Monitor gestartet (Zyklus: {READ_INTERVAL_S}s, Watchdog: {WATCHDOG_INTERVAL_S}s).")
    print(f"  EIN ab {TEMP_ON_THRESHOLD} C, AUS unter {TEMP_OFF_THRESHOLD} C")
    print("Beenden mit Strg+C.\n")

    print("Selbsttest: Steckdose wird fuer 3 Sekunden eingeschaltet ...")
    _fritz_switch(on=True)
    time.sleep(3)
    _fritz_switch(on=False)
    print("Selbsttest abgeschlossen.\n")

    _read_and_control()

    worker = threading.Thread(target=_loop, daemon=True)
    worker.start()

    try:
        worker.join()
    except KeyboardInterrupt:
        print("\nMonitor beendet.")
        _stop_event.set()
