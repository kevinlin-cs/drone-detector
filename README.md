# Aerial Signal Monitor — Remote ID + RF Drone Detection

A standalone, passive drone-detection system built on an ESP32-S3 and a Raspberry Pi Zero 2 W. It listens for FAA Remote ID broadcasts and flags unidentified nearby RF transmitters, streaming everything to a live web dashboard.

The whole system runs headless — power it on and the dashboard is served automatically, no laptop required.

---

## What it does

**Two detection layers:**

1. **Remote ID drones (confirmed aircraft).** The ESP32-S3 scans WiFi (NAN action frames + beacon vendor IEs, hopping channels 1–11) and Bluetooth LE for FAA-mandated Remote ID broadcasts, decoding them with the OpenDroneID standard. These carry a real identifier, GPS position, and altitude, so they plot at true coordinates with live flight trails.
   - *Limitation:* only detects drones that actually broadcast Remote ID — generally units over 250 g. Non-broadcasting or sub-250 g aircraft, and spoofed IDs, are invisible to this layer.

2. **RF candidates (unidentified transmitters).** Any WiFi/BLE signal that doesn't decode as Remote ID but whose signal strength swings enough to suggest motion is flagged as a lead. Derived only from a MAC address and RSSI — no protocol decode.
   - *Limitation:* no bearing or true position; range is a rough RSSI estimate drawn as a ring around the sensor. Cannot distinguish a drone from a phone, laptop, or any moving 2.4 GHz device. Treated as leads, not confirmed aircraft.

---

## Architecture

```
[ESP32-S3 "Board B"]  --USB serial-->  [Raspberry Pi Zero 2 W]  --WebSocket-->  [Browser dashboard]
  WiFi + BLE scanning                    FastAPI backend                          live map, contact
  Remote ID decode                       serial reader + broadcaster              lists, event feed
  RF-anomaly detection                   systemd auto-start service
  JSON over USB
```

- **Firmware** (`firmware/main_remote.cpp`): dual-core FreeRTOS — one core for WiFi promiscuous capture, one for BLE scanning. Detections are pushed through an ISR-safe queue to a printer task that emits JSON over USB serial. Includes a mutex-protected shared array (fixing an early race condition) and an RF-candidate tracker with per-MAC RSSI history, stationary-device suppression, and report cooldown to control false positives.
- **Backend** (`backend/dronepi_backend.py`): FastAPI + Uvicorn. Reads the serial stream with auto-reconnect, parses each JSON line, and broadcasts to all connected browsers over WebSocket. Serves the dashboard and a demo endpoint for injecting simulated drone flights.
- **Dashboard**: single-page Leaflet map + contact panels. Vendor OUI lookup, randomized-vs-hardware MAC classification, signal quality, estimated range, first-seen and detection counts, filtering/sorting, per-contact and bulk delete, an event ticker, and a demo control to launch N simulated drones.

---

## Hardware

- ESP32-S3 (Seeed XIAO ESP32-S3) — the "remote node" scanner
- Raspberry Pi Zero 2 W — headless host running the backend
- USB cable (Board B → Pi, carries both power and data)

---

## Running it

### Firmware
Flash `firmware/main_remote.cpp` to the ESP32-S3 with PlatformIO:
```bash
pio run -e remote_node -t upload
```

### Backend (on the Pi)
```bash
python3 -m venv --system-site-packages ~/dronepi-env
source ~/dronepi-env/bin/activate
pip install fastapi uvicorn websockets pyserial
python -m uvicorn dronepi_backend:app --host 0.0.0.0 --port 8000
```
Set `SENSOR_LAT` / `SENSOR_LON` at the top of `dronepi_backend.py` to the sensor's real location (this centers the candidate range rings).

### Auto-start on boot (systemd)
The backend runs as a service so it survives reboots and disconnects. See `systemd/dronepi.service`.

### View the dashboard
Open `http://<pi-ip>:8000` from any device on the same network.

### Demo mode
Use the **Demo** control in the header to launch simulated drones (or visit `http://<pi-ip>:8000/test?count=5`). Useful for testing the multi-drone tracking and dashboard without live aircraft.

---

## Status & limitations

- Fully working end to end: firmware, serial link, backend, dashboard, and auto-start are all verified.
- The Remote ID pipeline is validated with simulated flights. Live over-the-air validation against a real Remote-ID-broadcasting drone is the one remaining test (pending access to a compliant aircraft).
- Range is limited by the ESP32-S3's onboard antenna — roughly tens of meters for BLE, up to ~150 m line-of-sight for WiFi. An external antenna would extend this.
- The vendor OUI table is small and illustrative, not a complete registry.

## Legal note

This system is **passive** — it only receives publicly broadcast signals (Remote ID is designed to be publicly receivable; WiFi/BLE advertisements are sent in the clear). It does not transmit, jam, decrypt, or spoof anything. MAC addresses are personal data under some privacy regimes; if deploying beyond personal testing, consider hashing stored MACs and checking local/institutional policy.
