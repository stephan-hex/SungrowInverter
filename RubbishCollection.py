import csv
import os
import datetime

class RubbishCollection:
    def __init__(self, file_path):
        self.file_path = file_path
        self.collections = []  # Liste von Tupeln: (Datum, Kategorie)
        self._load_calendar()

    def _load_calendar(self):
        """Lädt die CSV-Datei und parst die Termine."""
        if not os.path.exists(self.file_path):
            print(f"Fehler: Datei {self.file_path} nicht gefunden.")
            return

        try:
            # Da die Datei Umlaute enthält (Hausmüll, Grüngut), nutzen wir latin-1 
            # oder utf-8 mit Fehlerbehandlung für das '' Zeichen.
            with open(self.file_path, mode='r', encoding='latin-1') as f:
                reader = csv.reader(f, delimiter=';')
                headers = next(reader)
                
                # Spaltennamen säubern und Leerzeichen entfernen
                categories = [h.strip() for h in headers]
                
                for row in reader:
                    for i, date_str in enumerate(row):
                        if date_str and date_str.strip():
                            try:
                                # Datum parsen: DD.MM.YYYY
                                date_obj = datetime.datetime.strptime(date_str.strip(), "%d.%m.%Y").date()
                                self.collections.append((date_obj, categories[i]))
                            except ValueError:
                                continue # Ungültiges Datumsformat ignorieren
        except Exception as e:
            print(f"Fehler beim Lesen der Kalenderdatei: {e}")

    def GetNextCollectionDates(self, days_in_future):
        """
        Gibt alle Abfuhrtermine innerhalb der nächsten X Tage zurück.
        Rückgabewert: Liste von Dictionaries [{'category': ..., 'date': ...}]
        """
        today = datetime.date.today()
        limit_date = today + datetime.timedelta(days=int(days_in_future))
        
        results = []
        for date_obj, category in self.collections:
            # Filter: Zwischen heute (inklusive) und dem Zieldatum
            if today <= date_obj <= limit_date:
                results.append({
                    'category': category,
                    'date': date_obj
                })
        
        # Sortierung nach Datum
        results.sort(key=lambda x: x['date'])
        return results

if __name__ == "__main__":
    # Pfad zur CSV Datei (relativ zum Skriptpfad)
    csv_path = os.path.join(os.path.dirname(__file__), "calendar.csv")
    
    print("--- Müllabfuhr Kalender Test ---")
    rubbish = RubbishCollection(csv_path)
    
    try:
        user_input = input("Für wie viele Tage in die Zukunft sollen Termine geprüft werden? ")
        days = int(user_input)
        
        next_dates = rubbish.GetNextCollectionDates(days)
        
        print(f"\nErgebnisse für die nächsten {days} Tage (ab heute, {datetime.date.today().strftime('%d.%m.%Y')}):")
        print("-" * 50)
        
        if not next_dates:
            print("Keine Termine in diesem Zeitraum gefunden.")
        else:
            for item in next_dates:
                # Wochentag ermitteln
                wd_map = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
                weekday = wd_map[item['date'].weekday()]
                
                print(f"{weekday:10} | {item['date'].strftime('%d.%m.%Y')} | {item['category']}")
        
        print("-" * 50)
        
    except ValueError:
        print("Ungültige Eingabe. Bitte eine Zahl eingeben.")
    except KeyboardInterrupt:
        print("\nProgramm beendet.")
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")