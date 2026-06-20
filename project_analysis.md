# Project Analysis: SungrowInverter Smart Home Central

This project is a Python-based home automation and monitoring central, designed to run headlessly on a Raspberry Pi (via [main_raspi.py](file:///Users/stephan/Programming/Python/SungrowInverter/main_raspi.py)) or on a local desktop machine (via [main.py](file:///Users/stephan/Programming/Python/SungrowInverter/main.py)). 

It coordinates power readings from a **Sungrow SH8-RT Inverter** with several smart home subsystems (Fritz!Box DECT switches, Homematic IP sensors, Go-eCharger EV wallbox, and custom ESP32 cistern depth sensors) to provide real-time dashboards, automation logic (intelligent surplus charging, temperature-controlled cooling fans), weekly email reporting, and historical data logging.

---

## 1. System Architecture

The following diagram shows how the background daemons, hardware components, local APIs, and user interfaces interact.

```mermaid
graph TD
    %% Hardware / Devices
    Inverter[Sungrow Inverter SH8-RT]
    FritzBox[Fritz!Box DECT Plugs<br/>Zisterne, Brunnen, Lüfter]
    CCU[Homematic CCU<br/>Windows, Thermostats]
    ESP32[ESP32 Ultrasonic Sensor<br/>Cistern Water Level]
    GoE[Go-eCharger Wallbox]
    GMX[GMX Mail Server]
    
    %% Python Backend Components
    subgraph Python Backend (main_raspi.py)
        DB[(SQLite Database<br/>pv_data.db)]
        Web[PV_Web Server<br/>Port 8080]
        
        %% Integration Modules
        Modbus[Modbus TCP client]
        FritzCtrl[fritz_control.py]
        HMCtrl[homematic_device_monitor.py]
        ESPCtrl[ESP32_Sensor_Reader.py]
        RubCtrl[RubbishCollection.py]
        
        %% Polling Loops
        FritzThread[Fritz Poll Thread]
        HMThread[Homematic Poll Thread]
        ESPThread[ESP32 Poll Thread]
        GoEThread[Go-e Poll Thread]
    end
    
    subgraph Intelligent Charger Daemon (go_e_control.py)
        GoEAuto[go_e_control.py<br/>Port 8081]
    end
    
    subgraph Inverter Fan Control (temp_monitor.py)
        FanMonitor[temp_monitor.py]
    end
    
    subgraph Weekly Reporter (weekly_report.py)
        Reporter[weekly_report.py]
    end

    %% Web Dashboards
    subgraph HTML Frontend (Dashboards)
        UI_Home[index.html - Hub]
        UI_PV[pv.html - Powerflow]
        UI_EV[charge.html - Wallbox]
        UI_Win[windows.html - Windows/Shutters]
        UI_Other[others.html - Cistern/Switches]
        UI_Hist[history.html - Charts]
    end

    %% Connections
    Inverter -- Modbus TCP --> Modbus
    Modbus --> DB
    Modbus --> Web
    
    %% FritzBox Plugs
    FritzCtrl -- AVM AHA API --> FritzBox
    FritzThread --> FritzCtrl
    FritzThread --> Web
    
    %% Homematic
    HMCtrl -- XML-RPC / TCLReGa --> CCU
    HMThread --> HMCtrl
    HMThread --> Web
    
    %% ESP32
    ESPCtrl -- HTTP JSON --> ESP32
    ESPThread --> ESPCtrl
    ESPThread --> Web
    
    %% Go-e Charger Integration
    GoEThread -- HTTP API (8081) --> GoEAuto
    GoEAuto -- HTTP API (Status/Set) --> GoE
    GoEAuto -- Fetch PV state --> Web
    
    %% Temp Monitor
    FanMonitor -- Poll temperature --> Web
    FanMonitor -- Switch Fan On/Off --> FritzBox
    
    %% Weekly Report
    Reporter -- Query weekly data --> DB
    Reporter -- DB backup --> DB
    Reporter -- Send email --> GMX
    
    %% Webserver routing
    Web --> UI_Home
    Web --> UI_PV
    Web --> UI_EV
    Web --> UI_Win
    Web --> UI_Other
    Web --> UI_Hist
```

---

## 2. Core Modules & Functionality

### 2.1 Web Server & Dashboards ([PV_Web.py](file:///Users/stephan/Programming/Python/SungrowInverter/PV_Web.py))
Serves a multi-threaded Python HTTP Server on port `8080` (with socket reuse and concurrent connection handling):
- **`/api`**: Serves a JSON document containing a merged cache of current Modbus readings, Fritz!Box states, Homematic variables, ESP32 levels, Go-e status, and rubbish dates.
- **`/api/history`**: Queries the SQLite database for a specified date and lists of columns, formatting it for `Chart.js` rendering.
- **`/action`**: Receives POST command payloads from frontend UI buttons (e.g. `mode_normal`, `mode_surplus`, `goe_start`, `goe_stop`, `fritz_<name>_<on/off>`) and forwards them to the respective service managers.

**Dashboard Interfaces:**
1. **Hub ([index.html](file:///Users/stephan/Programming/Python/SungrowInverter/index.html))**: Displays a responsive station clock (SVG-based Berlin-time clock), weather forecast from Open-Meteo, local outdoor temperature/humidity (queried via Homematic), rubbish collection calendar, and main menu buttons.
2. **PV Power Flow ([pv.html](file:///Users/stephan/Programming/Python/SungrowInverter/pv.html))**: Animates energy flows between Solar Panels $\rightarrow$ Battery (charging/discharging) $\rightarrow$ Household consumption, displaying raw metrics and battery state-of-charge segment bars.
3. **EV Charging Control ([charge.html](file:///Users/stephan/Programming/Python/SungrowInverter/charge.html))**: Displays wallbox active power, session usage, vehicle attachment status, and charging mode toggles.
4. **Window Status ([windows.html](file:///Users/stephan/Programming/Python/SungrowInverter/windows.html))**: Filters and highlights only currently open window contacts and lists shutter level symbols ($\uparrow$, $\downarrow$, $\leftrightarrow$).
5. **Cistern & Switches ([others.html](file:///Users/stephan/Programming/Python/SungrowInverter/others.html))**: Visualizes the water depth of the rain-water cistern and switches the Fritz!Box smart plugs with debounce timers to avoid toggle flickers.
6. **Charts History ([history.html](file:///Users/stephan/Programming/Python/SungrowInverter/history.html))**: Employs Chart.js to render dual-axis historical charts for power lines (in Watts) and battery state-of-charge (in %).

---

### 2.2 Modbus TCP Inverter Interface ([main_raspi.py](file:///Users/stephan/Programming/Python/SungrowInverter/main_raspi.py))
Reads operational registers from the inverter (Unit ID `1`, port `502`) using Modbus TCP. It handles:
- **Automatic Word Swapping**: Many 32-bit values in Sungrow register maps use "Swapped Words" (`uint32sw` / `int32sw` where the high and low 16-bit words are swapped). The backend automatically reconstructs them:
  $$\text{val} = (\text{regs}[1] \ll 16) \mid \text{regs}[0]$$
- **Connection Retry Logic**: Attempts register reads up to 3 times on connection errors (e.g., Modbus timeouts/dongle resets), pausing $0.05\text{s}$ between queries to prevent overloading the WiNet-S module.
- **Factor Correction**: Multiplies raw integers by scale factors (defined in [registers.json](file:///Users/stephan/Programming/Python/SungrowInverter/registers.json)) to get correct decimal measurements (e.g. $0.1$ for temperatures or kWh).

---

### 2.3 Database Management ([PV_Database.py](file:///Users/stephan/Programming/Python/SungrowInverter/PV_Database.py))
Provides robust time-series logging to `pv_data.db`:
- **WAL Journaling**: Configures `PRAGMA journal_mode=WAL;` to allow simultaneous reads (from the Web API / history charts) and writes (from background thread tasks) without locking the file.
- **Buffer Averaging (Pi SD Card Protection)**: To reduce continuous disk wear on memory cards, Modbus readings are accumulated in memory every $5\text{s}$. Every $60\text{s}$ (the `DB_UPDATE_INTERVAL`), the daemon calculates average values for all registers and inserts a single consolidated record.

---

## 3. Automation and Integration Scripts

### 3.1 Go-e Charger Surplus Control ([go_e_control.py](file:///Users/stephan/Programming/Python/SungrowInverter/go_e_control.py))
Coordinates intelligent EV charging using excess solar energy:
- Runs an API server on port `8081` to receive commands (`/api/set`) and publish wallbox status (`/api/status`).
- **INTELLIGENT-CHARGING Algorithm**:
  - **Start Threshold**: If the vehicle is plugged in and the home storage battery SOC rises $\ge 80\%$, the charger is switched to 3-phase mode (`psm=2`) and begins charging at the baseline current ($6\text{A}$, equivalent to $\approx 4.1\text{kW}$).
  - **Phase Fallback (1-phase)**: If the PV battery SOC drops $< 75\%$, the wallbox switches to 1-phase mode (`psm=1`) to continue charging at lower power thresholds ($1.3\text{kW}$ to $2.7\text{kW}$).
  - **Dynamic Boosting**: While in 1-phase mode, if the PV battery SOC rises (due to solar surplus), the current is stepped up in $2\text{A}$ increments up to $12\text{A}$ ($2.7\text{kW}$).
  - **Stop Threshold**: If the PV battery SOC drops $< 70\%$, charging is stopped entirely to preserve home electricity.
  - **Reset**: Swapping back to `NORMAL-CHARGING` resets the wallbox to standard manual operation ($16\text{A}$, 3-phase, $\approx 11\text{kW}$).

---

### 3.2 Inverter Active Cooling ([temp_monitor.py](file:///Users/stephan/Programming/Python/SungrowInverter/temp_monitor.py))
Controls an external ventilation fan to cool the inverter chassis:
- **Loop**: Queries the local PV web server API every $60\text{s}$ for `internal_temperature`.
- **Hysteresis Control**:
  - If Temperature $\ge 45^\circ\text{C}$: Turns on the Fritz!Box DECT smart plug connected to the cooling fan.
  - If Temperature $< 42^\circ\text{C}$: Turns the cooling fan plug off.
- **Watchdog Guard**: Every 5 minutes, checks if the smart plug's actual switch state matches the intended state (verifying physical presence/reachability) and logs errors or corrects anomalies.

---

### 3.3 Homematic IP Monitor ([homematic_device_monitor.py](file:///Users/stephan/Programming/Python/SungrowInverter/homematic_device_monitor.py))
Polls HomeMatic IP devices using TCL ReGa scripts sent directly to CCU port `8181`:
- Dynamically compiles a script requesting state values for all devices configured in [homematic_device_config.json](file:///Users/stephan/Programming/Python/SungrowInverter/homematic_device_config.json).
- Supports parsing variables based on datatype definitions (`bool`, `float`, `int`, etc.).
- Categorizes queries into status reads, low-battery alerts (`check_low_bat`), and temperature/humidity updates.
- **Hybrid-Interval Polling**: Polling occurs every $30\text{s}$ when the web dashboard is actively open (triggered by the `/windows.html` request header), and dials back to a low-frequency $300\text{s}$ check when idle.

---

### 3.4 ESP32 Cistern Depth Sensor ([ESP32_Sensor_Reader.py](file:///Users/stephan/Programming/Python/SungrowInverter/ESP32_Sensor_Reader.py))
Parses JSON payloads from an ESP32 micro-controller reading water levels:
- Reads the ultrasonic echo duration to determine distance ($d$) in cm.
- Computes Füllstand (fill level %) with a linear scaling between configurable minimum and maximum sensor distance limits:
  $$\text{percent} = 100.0 - \left(\frac{d - d_{\text{min}}}{d_{\text{max}} - d_{\text{min}}} \times 100.0\right)$$
- If the sensor fails, it preserves the last valid measurement in the cache and triggers a warning state (`zisterne_stale`) on the web dashboard if no update is received for over 5 minutes.

---

### 3.5 Rubbish Calendar ([RubbishCollection.py](file:///Users/stephan/Programming/Python/SungrowInverter/RubbishCollection.py))
Ingests local waste collection dates from `calendar.csv` (semi-colon separated, parsed in `latin-1` to preserve German characters):
- Maps columns to trash categories (e.g. Hausmüll, Grüngut, Gelber Sack).
- Filters dates between today and the next 3 days, sorting them chronologically for display on the main dashboard hub.

---

### 3.6 Weekly Reports & Backups ([weekly_report.py](file:///Users/stephan/Programming/Python/SungrowInverter/weekly_report.py))
Designed to be triggered weekly (e.g., via cron):
- **Hot Database Backup**: Performs a live, non-blocking backup of the SQLite database:
  `conn.backup(backup_conn)`
  Saves backups as `pv_db_backup_cw{week}_{year}.db` for robust data preservation.
- **Data Summarization**: Computes daily totals for PV yield, net import, net export, and calculates self-consumption:
  $$\text{Self Consumption} = \text{PV Yield} - \text{Net Export}$$
- **Email Delivery**: Connects to SMTP (default: GMX) using credentials from [mail_credentials.json](file:///Users/stephan/Programming/Python/SungrowInverter/mail_credentials.json). Dispatches a formatted monospaced table using plain text and HTML components.

---

## 4. Key Files & Configuration Files

| File | Type | Description |
| :--- | :--- | :--- |
| [main_raspi.py](file:///Users/stephan/Programming/Python/SungrowInverter/main_raspi.py) | Python Script | Primary background server daemon. |
| [registers.json](file:///Users/stephan/Programming/Python/SungrowInverter/registers.json) | Configuration | Map of Inverter Modbus register addresses, data types, and scale factors. |
| [fritz_config.json](file:///Users/stephan/Programming/Python/SungrowInverter/fritz_config.json) | Configuration | IP address, credentials, and DECT smart plug AIN identifiers. |
| [homematic_device_config.json](file:///Users/stephan/Programming/Python/SungrowInverter/homematic_device_config.json) | Configuration | Addresses, channels, and types of Homematic IP sensors. |
| [CCU_credentials.json](file:///Users/stephan/Programming/Python/SungrowInverter/CCU_credentials.json) | Configuration | CCU IP address, username, and password. |
| [mail_credentials.json](file:///Users/stephan/Programming/Python/SungrowInverter/mail_credentials.json) | Configuration | SMTP server details for weekly report emails. |
| [ESP32_Sensor_config.json](file:///Users/stephan/Programming/Python/SungrowInverter/ESP32_Sensor_config.json) | Configuration | IP address and cistern ultrasonic limits ($80\text{cm}$ - $160\text{cm}$). |
| [calendar.csv](file:///Users/stephan/Programming/Python/SungrowInverter/calendar.csv) | Data | Waste collection dates and category columns. |
| [pv_data.db](file:///Users/stephan/Programming/Python/SungrowInverter/pv_data.db) | SQLite Database | Primary time-series readings database. |

---

## 5. Potential Future Improvements

1. **Error Resiliency for Missing Hardware**: If one of the integrations (e.g. Fritz!Box or Homematic) is offline, the backend threads catch the errors but print warnings. A standardized retry-backoff strategy for HTTP requests could make polling loops more resilient.
2. **Modern Web UI Design**: The HTML templates use simple, solid-color styling and legacy fonts. Implementing a unified design system (e.g., using custom CSS properties, flexbox grids, glassmorphism, or modern typography from Google Fonts) would make the dashboards look premium.
3. **API Security**: The web interface does not use authentication or HTTPS. If port `8080` is exposed outside the local network, anyone can trigger POST actions on the switches and chargers. Basic token/session auth or local network binding validation would secure endpoints.
4. **Heating/Cooling Dashboard**: The [heating-cooling.html](file:///Users/stephan/Programming/Python/SungrowInverter/heating-cooling.html) file is currently a placeholder ("under construction"). Integrating the Homematic thermostats' current temperature, target setpoint, and valve positions would complete this dashboard.
5. **Standard Systemd Services**: Setting up simple service files for `main_raspi.py`, `temp_monitor.py`, and `go_e_control.py` ensures these scripts run automatically on Raspberry Pi boot and restart on failure.
