# log error messages into a file. Fefault is: error_msg.log

import os
import datetime

class PV_Logger:
    def __init__(self, filename="error_msg.log", max_size_mb=5):
        """
        Initialisiert den Logger. 
        Prüft beim Start, ob das Logfile bereits existiert.
        :param max_size_mb: Limit in Megabyte (Standard: 5 MB).
        """
        self.filepath = os.path.join(os.path.dirname(__file__), filename)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        
        if os.path.exists(self.filepath):
            print(f"Logfile gefunden: {self.filepath}")
        else:
            print(f"Logfile nicht gefunden. Es wird bei Bedarf neu erstellt: {self.filepath}")

    def _rotate_if_needed(self):
        """Prüft die Dateigröße und rotiert, falls Limit überschritten (.log -> .log.1)"""
        if not os.path.exists(self.filepath):
            return
            
        try:
            # Größe in Bytes prüfen
            if os.path.getsize(self.filepath) > self.max_size_bytes:
                backup_path = self.filepath + ".1"
                # Altes Backup löschen, falls vorhanden
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                # Aktuelles Log umbenennen
                os.rename(self.filepath, backup_path)
                print(f"Log-Rotation durchgeführt: {os.path.basename(self.filepath)} wurde zu {os.path.basename(backup_path)}")
        except Exception as e:
            print(f"Fehler bei der Log-Rotation: {e}")

    def log_error(self, message):
        """Schreibt eine Fehlermeldung mit Zeitstempel in das Logfile."""
        self._rotate_if_needed()
        
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}\n"
        
        try:
            # 'a' (append) öffnet die Datei zum Anhängen oder erstellt sie neu, falls nicht vorhanden.
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            print(f"KRITISCHER FEHLER: Konnte nicht ins Logfile schreiben: {e}")