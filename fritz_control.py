import urllib.request
import urllib.parse
import hashlib
import xml.etree.ElementTree as ET
import time

class FritzControl:
    def __init__(self, config):
        self.config = config
        self.sid = "0000000000000000"
        self.last_sid_check = 0

    def get_sid(self):
        """Ermittelt eine gültige SID. Nutzt Cache für 10 Minuten."""
        now = time.time()
        if self.sid != "0000000000000000" and (now - self.last_sid_check < 600):
            return self.sid

        try:
            base_url = f"http://{self.config['fritz_ip']}/login_sid.lua"
            # Aktuellen Status prüfen
            with urllib.request.urlopen(base_url, timeout=10) as r:
                root = ET.fromstring(r.read())
            
            challenge = root.findtext("Challenge")
            sid = root.findtext("SID")

            if sid and sid != "0000000000000000":
                self.sid = sid
                self.last_sid_check = now
                return self.sid

            # Login-Response berechnen
            hash_str = f"{challenge}-{self.config['fritz_password']}"
            md5_res = hashlib.md5(hash_str.encode("utf-16-le")).hexdigest()
            response = f"{challenge}-{md5_res}"
            
            params = urllib.parse.urlencode({
                "username": self.config["fritz_user"], 
                "response": response
            })
            
            with urllib.request.urlopen(f"{base_url}?{params}", timeout=10) as r:
                root = ET.fromstring(r.read())
                self.sid = root.findtext("SID")
            
            self.last_sid_check = time.time()
            return self.sid
        except Exception as e:
            print(f"[FritzControl] Login Fehler: {e}")
            self.sid = "0000000000000000"
            return None

    def switch(self, ain, on):
        """Schaltet eine Steckdose ein oder aus."""
        sid = self.get_sid()
        if not sid: return False
        try:
            ain = ain.replace(" ", "")
            cmd = "setswitchon" if on else "setswitchoff"
            params = urllib.parse.urlencode({"ain": ain, "switchcmd": cmd, "sid": sid})
            url = f"http://{self.config['fritz_ip']}/webservices/homeautoswitch.lua?{params}" # timeout=10
            with urllib.request.urlopen(url, timeout=3) as r:
                r.read() # AHA liefert den neuen Zustand zurück
            return True
        except Exception as e:
            print(f"[FritzControl] Switch Fehler für {ain}: {e}")
            self.sid = "0000000000000000" # SID bei Fehler zurücksetzen
            return False

    def get_state(self, ain):
        """Gibt den Schaltzustand zurück ('1', '0' oder 'inval')."""
        sid = self.get_sid()
        if not sid: return "inval"
        try:
            ain = ain.replace(" ", "")
            params = urllib.parse.urlencode({"ain": ain, "switchcmd": "getswitchstate", "sid": sid})
            url = f"http://{self.config['fritz_ip']}/webservices/homeautoswitch.lua?{params}"
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.read().decode("utf-8").strip()
        except:
            self.sid = "0000000000000000"
            return "inval"