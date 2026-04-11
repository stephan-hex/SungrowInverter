import sqlite3
import datetime
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Konfiguration
DB_PATH = os.path.join(os.path.dirname(__file__), "pv_data.db")
MAIL_CFG_PATH = os.path.join(os.path.dirname(__file__), "mail_credentials.json")

def get_last_full_week_range():
    """Berechnet Start (Montag 0:00) und Ende (Sonntag 23:59) der letzten vollen Woche."""
    today = datetime.date.today()
    # weekday() ist 0 für Montag, 6 für Sonntag
    # Wir gehen zurück zum letzten Sonntag
    last_sunday = today - datetime.timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - datetime.timedelta(days=6)
    
    start_dt = datetime.datetime.combine(last_monday, datetime.time.min)
    end_dt = datetime.datetime.combine(last_sunday, datetime.time.max)
    
    return start_dt, end_dt

def fetch_day_totals(conn, day_dt):
    """Holt den letzten verfügbaren Messwert eines spezifischen Tages."""
    start_ts = datetime.datetime.combine(day_dt, datetime.time.min).timestamp()
    end_ts = datetime.datetime.combine(day_dt, datetime.time.max).timestamp()
    
    query = """
        SELECT daily_pv_generation, daily_import_energy, daily_export_energy 
        FROM readings 
        WHERE timestamp BETWEEN ? AND ? 
        ORDER BY timestamp DESC 
        LIMIT 1
    """
    
    cursor = conn.cursor()
    cursor.execute(query, (start_ts, end_ts))
    return cursor.fetchone()

def send_mail(report_text, subject):
    """Versendet den Bericht per GMX SMTP."""
    if not os.path.exists(MAIL_CFG_PATH):
        template = {
            "smtp_server": "mail.gmx.net",
            "smtp_port": 587,
            "user": "DEINE_EMAIL@gmx.de",
            "password": "DEIN_PASSWORT",
            "recipient": "EMPFAENGER_EMAIL@domain.de"
        }
        with open(MAIL_CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(template, f, indent=4)
        print(f"\nHINWEIS: Die Datei '{os.path.basename(MAIL_CFG_PATH)}' wurde nicht gefunden und als Template neu erstellt.")
        print("Bitte trage dort deine Mail-Zugangsdaten ein, damit der Bericht versendet werden kann.\n")
        return

    with open(MAIL_CFG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    msg = MIMEMultipart('alternative')
    msg['From'] = cfg['user']
    msg['To'] = cfg['recipient']
    msg['Subject'] = subject

    # Plain-Text Version (Fallback)
    msg.attach(MIMEText(report_text, 'plain', 'utf-8'))

    # HTML-Version mit Monospace-Schriftart, um die Spaltenausrichtung zu erzwingen
    html_content = f"<html><body><pre style=\"font-family: 'Courier New', Courier, monospace; font-size: 12px;\">{report_text}</pre></body></html>"
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port'])
        server.starttls()  # GMX erfordert STARTTLS
        server.login(cfg['user'], cfg['password'])
        server.send_message(msg)
        server.quit()
        print("E-Mail erfolgreich versendet.")
    except Exception as e:
        print(f"Fehler beim E-Mail-Versand: {e}")

def generate_report():
    if not os.path.exists(DB_PATH):
        print(f"Fehler: Datenbank nicht gefunden unter {DB_PATH}")
        return

    start_week, end_week = get_last_full_week_range()
    iso_year, iso_week, _ = start_week.isocalendar()
    report_lines = []

    report_lines.append("="*60)
    report_lines.append(f"WOCHENBERICHT KW {iso_week} ({iso_year})")
    report_lines.append(f"Zeitraum: {start_week.strftime('%d.%m.%Y')} bis {end_week.strftime('%d.%m.%Y')}")
    report_lines.append("="*60)
    report_lines.append(f"{'Tag':<12} | {'PV Ertrag':>12} | {'Netzbezug':>12} | {'Einspeisung':>12}")
    report_lines.append("-"*60)

    total_pv = 0.0
    total_import = 0.0
    total_export = 0.0
    days_found = 0

    try:
        conn = sqlite3.connect(DB_PATH)
        
        # Iteriere über alle 7 Tage der Woche
        for i in range(7):
            current_day = start_week.date() + datetime.timedelta(days=i)
            row = fetch_day_totals(conn, current_day)
            
            day_name = current_day.strftime("%A")
            # Deutsche Wochentage (optional)
            translations = {
                "Monday": "Montag", "Tuesday": "Dienstag", "Wednesday": "Mittwoch",
                "Thursday": "Donnerstag", "Friday": "Freitag", "Saturday": "Samstag", "Sunday": "Sonntag"
            }
            display_name = translations.get(day_name, day_name)

            if row:
                pv, imp, exp = [val if val is not None else 0.0 for val in row]
                report_lines.append(f"{display_name:<12} | {pv:10.2f} kWh | {imp:10.2f} kWh | {exp:10.2f} kWh")
                
                total_pv += pv
                total_import += imp
                total_export += exp
                days_found += 1
            else:
                report_lines.append(f"{display_name:<12} | {'Keine Daten':>12} | {'-':>12} | {'-':>12}")

        conn.close()

        report_lines.append("-"*60)
        report_lines.append(f"{'GESAMT':<12} | {total_pv:10.2f} kWh | {total_import:10.2f} kWh | {total_export:10.2f} kWh")
        report_lines.append("="*60)
        
        if days_found < 7:
            report_lines.append(f"Hinweis: Der Bericht ist unvollständig ({days_found}/7 Tage gefunden).")
            
        direkt_verbrauch = total_pv - total_export
        report_lines.append(f"Direktverbrauch aus PV: {max(0, direkt_verbrauch):.2f} kWh")

        full_report = "\n".join(report_lines)
        print(full_report)
        
        # Versand per E-Mail
        subject = f"Weekly PV Report {iso_week} {iso_year}"
        send_mail(full_report, subject)

    except Exception as e:
        print(f"Fehler beim Erstellen des Berichts: {e}")

if __name__ == "__main__":
    generate_report()