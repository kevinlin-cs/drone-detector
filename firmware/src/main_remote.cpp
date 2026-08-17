/*
 * =============================================================================
 * REMOTE NODE - Drone Remote ID Detector + Mesh Sender
 * colonelpanichacks
 *
 * Dual-core ESP32S3 firmware:
 *   Core 0: WiFi promiscuous packet sniffing (Open Drone ID NAN/Beacon)
 *   Core 1: BLE scanning (Open Drone ID BLE advertisements)
 *
 * Detected drone JSON is sent to:
 *   - USB Serial (for local monitoring / direct mesh-mapper.py connection)
 *   - Serial1 UART (GPIO5 TX / GPIO6 RX -> Heltec V3 running Meshtastic)
 *
 * JSON format (matches mesh-mapper.py API, includes node_id for dedup):
 *   {"mac":"xx:xx:xx:xx:xx:xx","rssi":-50,"drone_lat":0.0,"drone_long":0.0,
 *    "drone_altitude":0,"pilot_lat":0.0,"pilot_long":0.0,"basic_id":"...",
 *    "node_id":"A1B2"}
 * =============================================================================
 */

#if !defined(ARDUINO_ARCH_ESP32)
  #error "This program requires an ESP32S3"
#endif

#include <Arduino.h>
#include <HardwareSerial.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <nvs_flash.h>
#include "opendroneid.h"
#include "odid_wifi.h"
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// =============================================================================
// Pin Definitions
// =============================================================================
// UART to Heltec V3 (Meshtastic)
static const int SERIAL1_TX_PIN = 5;   // GPIO5 -> Heltec RX
static const int SERIAL1_RX_PIN = 6;   // GPIO6 <- Heltec TX

// LED on XIAO ESP32S3 (active LOW / inverted logic)
#define LED_PIN 21

// =============================================================================
// Unique Node ID (derived from ESP32 MAC at boot)
// Used by home node to deduplicate detections from multiple remote nodes
// =============================================================================
static char nodeId[5] = "0000";  // 4-char hex, e.g. "A1B2"

static void generateNodeId() {
  uint8_t mac[6];
  esp_efuse_mac_get_default(mac);
  // Use last 2 bytes of factory MAC -> unique 4-hex-char ID per board
  snprintf(nodeId, sizeof(nodeId), "%02X%02X", mac[4], mac[5]);
}

// =============================================================================
// UAV Tracking
// =============================================================================
struct uav_data {
  uint8_t  mac[6];
  int      rssi;
  uint32_t last_seen;
  char     op_id[ODID_ID_SIZE + 1];
  char     uav_id[ODID_ID_SIZE + 1];
  double   lat_d;
  double   long_d;
  double   base_lat_d;
  double   base_long_d;
  int      altitude_msl;
  int      height_agl;
  int      speed;
  int      heading;
  int      flag;
};

#define MAX_UAVS 8
static uav_data uavs[MAX_UAVS] = {0};
static BLEScan* pBLEScan = nullptr;
static ODID_UAS_Data UAS_data;
static unsigned long last_status = 0;

// Thread-safe print queue (BLE callback + WiFi ISR -> printer task)
static QueueHandle_t printQueue;

// --- RF candidate tracking (non-Remote-ID transmitters) ---
#define MAX_SIGHTINGS 40
#define RSSI_HISTORY_LEN 5
#define STATIONARY_RSSI_TOLERANCE 12
#define STATIONARY_TIME_THRESHOLD 120000UL
#define MOVEMENT_RSSI_DELTA 20
#define REPORT_COOLDOWN 30000UL   // only report the same MAC once per 30s

struct rf_sighting {
  uint8_t mac[6];
  unsigned long first_seen;
  unsigned long last_seen;
  unsigned long last_reported;
  int rssi_history[RSSI_HISTORY_LEN];
  int history_index;
  int history_count;
  bool known_stationary;
};

struct rf_candidate_msg {
  uint8_t mac[6];
  int rssi;
};

static rf_sighting sightings[MAX_SIGHTINGS] = {0};
static QueueHandle_t rfQueue;

// Forward declarations
void callback(void *, wifi_promiscuous_pkt_type_t);

// =============================================================================
// UAV Slot Management
// =============================================================================
static uav_data* next_uav(uint8_t* mac) {
  // First: find existing entry for this MAC
  for (int i = 0; i < MAX_UAVS; i++) {
    if (memcmp(uavs[i].mac, mac, 6) == 0)
      return &uavs[i];
  }
  // Second: find empty slot
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].mac[0] == 0)
      return &uavs[i];
  }
  // Fallback: evict oldest entry
  uint32_t oldest_time = UINT32_MAX;
  int oldest_idx = 0;
  for (int i = 0; i < MAX_UAVS; i++) {
    if (uavs[i].last_seen < oldest_time) {
      oldest_time = uavs[i].last_seen;
      oldest_idx = i;
    }
  }
  return &uavs[oldest_idx];
}

static rf_sighting* find_or_create_sighting(uint8_t* mac) {
  // First: existing entry for this MAC
  for (int i = 0; i < MAX_SIGHTINGS; i++) {
    if (memcmp(sightings[i].mac, mac, 6) == 0) return &sightings[i];
  }
  // Second: empty slot
  for (int i = 0; i < MAX_SIGHTINGS; i++) {
    if (sightings[i].mac[0] == 0 && sightings[i].mac[1] == 0) {
      memcpy(sightings[i].mac, mac, 6);
      sightings[i].first_seen = millis();
      sightings[i].history_count = 0;
      sightings[i].history_index = 0;
      sightings[i].last_reported = 0;
      sightings[i].known_stationary = false;
      return &sightings[i];
    }
  }
   // Third: evict the stalest entry (longest since last seen)
  unsigned long oldest = ULONG_MAX;
  int oldest_idx = 0;
  for (int i = 0; i < MAX_SIGHTINGS; i++) {
    if (sightings[i].last_seen < oldest) {
      oldest = sightings[i].last_seen;
      oldest_idx = i;
    }
  }
  rf_sighting* s = &sightings[oldest_idx];
  memcpy(s->mac, mac, 6);
  s->first_seen = millis();
  s->history_count = 0;
  s->history_index = 0;
  s->last_reported = 0;
  s->known_stationary = false;
  return s;
}

static bool record_and_classify(rf_sighting* s, int rssi) {
  unsigned long now = millis();
  s->last_seen = now;
  s->rssi_history[s->history_index] = rssi;
  s->history_index = (s->history_index + 1) % RSSI_HISTORY_LEN;
  if (s->history_count < RSSI_HISTORY_LEN) { s->history_count++; return false; }

  int minR = 999, maxR = -999;
  for (int i = 0; i < s->history_count; i++) {
    if (s->rssi_history[i] < minR) minR = s->rssi_history[i];
    if (s->rssi_history[i] > maxR) maxR = s->rssi_history[i];
  }
  int spread = maxR - minR;

  if ((now - s->first_seen) > STATIONARY_TIME_THRESHOLD && spread < STATIONARY_RSSI_TOLERANCE)
    s->known_stationary = true;
  if (s->known_stationary) return false;

  return (spread >= MOVEMENT_RSSI_DELTA);
}

// Called from BLE + WiFi callbacks - queues a candidate, never prints directly
static void track_rf_sighting(uint8_t* mac, int rssi) {
  // sanity: reject implausible readings
  if (rssi > -20 || rssi < -95) return;
  
  rf_sighting* s = find_or_create_sighting(mac);
  if (!s) return;
  if (!record_and_classify(s, rssi)) return;

  unsigned long now = millis();
  if (s->last_reported != 0 && (now - s->last_reported) < REPORT_COOLDOWN) return;
  s->last_reported = now;

  rf_candidate_msg msg;
  memcpy(msg.mac, mac, 6);
  msg.rssi = rssi;
  BaseType_t woken = pdFALSE;
  xQueueSendFromISR(rfQueue, &msg, &woken);
  if (woken) portYIELD_FROM_ISR();
}


// =============================================================================
// BLE Advertisement Callback - Open Drone ID over BLE
// =============================================================================
class DroneIDCallback : public BLEAdvertisedDeviceCallbacks {
public:
  void onResult(BLEAdvertisedDevice device) override {
    int len = device.getPayloadLength();
    if (len <= 5) return;

    uint8_t* payload = device.getPayload();
    // Check for ODID BLE service data: type=0x16, UUID=0xFFFA, counter=0x0D
    // edited code
    if (payload[1] != 0x16 || payload[2] != 0xFA ||
        payload[3] != 0xFF || payload[4] != 0x0D) {
      track_rf_sighting((uint8_t*)device.getAddress().getNative(), device.getRSSI());
      return;
    }

    uint8_t* mac = (uint8_t*)device.getAddress().getNative();
    uav_data* UAV = next_uav(mac);
    UAV->last_seen = millis();
    UAV->rssi = device.getRSSI();
    UAV->flag = 1;
    memcpy(UAV->mac, mac, 6);

    uint8_t* odid = &payload[6];
    switch (odid[0] & 0xF0) {
      case 0x00: {  // Basic ID
        ODID_BasicID_data basic;
        decodeBasicIDMessage(&basic, (ODID_BasicID_encoded*)odid);
        strncpy(UAV->uav_id, (char*)basic.UASID, ODID_ID_SIZE);
        break;
      }
      case 0x10: {  // Location
        ODID_Location_data loc;
        decodeLocationMessage(&loc, (ODID_Location_encoded*)odid);
        UAV->lat_d = loc.Latitude;
        UAV->long_d = loc.Longitude;
        UAV->altitude_msl = (int)loc.AltitudeGeo;
        UAV->height_agl = (int)loc.Height;
        UAV->speed = (int)loc.SpeedHorizontal;
        UAV->heading = (int)loc.Direction;
        break;
      }
      case 0x40: {  // System (operator location)
        ODID_System_data sys;
        decodeSystemMessage(&sys, (ODID_System_encoded*)odid);
        UAV->base_lat_d = sys.OperatorLatitude;
        UAV->base_long_d = sys.OperatorLongitude;
        break;
      }
      case 0x50: {  // Operator ID
        ODID_OperatorID_data op;
        decodeOperatorIDMessage(&op, (ODID_OperatorID_encoded*)odid);
        strncpy(UAV->op_id, (char*)op.OperatorId, ODID_ID_SIZE);
        break;
      }
    }

    // Queue for printing (non-blocking, ISR-safe)
    uav_data tmp = *UAV;
    BaseType_t woken = pdFALSE;
    xQueueSendFromISR(printQueue, &tmp, &woken);
    if (woken) portYIELD_FROM_ISR();
  }
};

// =============================================================================
// WiFi Promiscuous Callback - Open Drone ID over WiFi (NAN + Beacon)
// =============================================================================
void callback(void *buffer, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT) return;

  wifi_promiscuous_pkt_t *packet = (wifi_promiscuous_pkt_t *)buffer;
  uint8_t *payload = packet->payload;
  int length = packet->rx_ctrl.sig_len;
  bool matched = false;

  // --- NAN Action Frame (WiFi Aware / Neighbor Awareness Networking) ---
  static const uint8_t nan_dest[6] = {0x51, 0x6f, 0x9a, 0x01, 0x00, 0x00};
  if (memcmp(nan_dest, &payload[4], 6) == 0) {
    if (odid_wifi_receive_message_pack_nan_action_frame(&UAS_data, nullptr, payload, length) == 0) {
      uav_data UAV;
      memset(&UAV, 0, sizeof(UAV));
      memcpy(UAV.mac, &payload[10], 6);
      UAV.rssi = packet->rx_ctrl.rssi;
      UAV.last_seen = millis();

      if (UAS_data.BasicIDValid[0])
        strncpy(UAV.uav_id, (char *)UAS_data.BasicID[0].UASID, ODID_ID_SIZE);
      if (UAS_data.LocationValid) {
        UAV.lat_d = UAS_data.Location.Latitude;
        UAV.long_d = UAS_data.Location.Longitude;
        UAV.altitude_msl = (int)UAS_data.Location.AltitudeGeo;
        UAV.height_agl = (int)UAS_data.Location.Height;
        UAV.speed = (int)UAS_data.Location.SpeedHorizontal;
        UAV.heading = (int)UAS_data.Location.Direction;
      }
      if (UAS_data.SystemValid) {
        UAV.base_lat_d = UAS_data.System.OperatorLatitude;
        UAV.base_long_d = UAS_data.System.OperatorLongitude;
      }
      if (UAS_data.OperatorIDValid)
        strncpy(UAV.op_id, (char *)UAS_data.OperatorID.OperatorId, ODID_ID_SIZE);

      uav_data* stored = next_uav(UAV.mac);
      *stored = UAV;
      stored->flag = 1;
      matched = true;

      uav_data tmp = *stored;
      BaseType_t woken = pdFALSE;
      xQueueSendFromISR(printQueue, &tmp, &woken);
      if (woken) portYIELD_FROM_ISR();
    }
     if (!matched) track_rf_sighting(&payload[10], packet->rx_ctrl.rssi);
    return;
  }

  // --- Beacon Frame with ODID vendor-specific IE ---
  if (payload[0] == 0x80) {
    int offset = 36;
    while (offset < length) {
      int typ = payload[offset];
      int len = payload[offset + 1];
      if (offset + len + 2 > length) break;  // bounds check

      if ((typ == 0xdd) &&
          (((payload[offset + 2] == 0x90 && payload[offset + 3] == 0x3a && payload[offset + 4] == 0xe6)) ||
           ((payload[offset + 2] == 0xfa && payload[offset + 3] == 0x0b && payload[offset + 4] == 0xbc)))) {
        int j = offset + 7;
        if (j < length) {
          memset(&UAS_data, 0, sizeof(UAS_data));
          odid_message_process_pack(&UAS_data, &payload[j], length - j);

          uav_data UAV;
          memset(&UAV, 0, sizeof(UAV));
          memcpy(UAV.mac, &payload[10], 6);
          UAV.rssi = packet->rx_ctrl.rssi;
          UAV.last_seen = millis();

          if (UAS_data.BasicIDValid[0])
            strncpy(UAV.uav_id, (char *)UAS_data.BasicID[0].UASID, ODID_ID_SIZE);
          if (UAS_data.LocationValid) {
            UAV.lat_d = UAS_data.Location.Latitude;
            UAV.long_d = UAS_data.Location.Longitude;
            UAV.altitude_msl = (int)UAS_data.Location.AltitudeGeo;
            UAV.height_agl = (int)UAS_data.Location.Height;
            UAV.speed = (int)UAS_data.Location.SpeedHorizontal;
            UAV.heading = (int)UAS_data.Location.Direction;
          }
          if (UAS_data.SystemValid) {
            UAV.base_lat_d = UAS_data.System.OperatorLatitude;
            UAV.base_long_d = UAS_data.System.OperatorLongitude;
          }
          if (UAS_data.OperatorIDValid)
            strncpy(UAV.op_id, (char *)UAS_data.OperatorID.OperatorId, ODID_ID_SIZE);

          uav_data* stored = next_uav(UAV.mac);
          *stored = UAV;
          stored->flag = 1;
          matched = true;

          uav_data tmp = *stored;
          BaseType_t woken = pdFALSE;
          xQueueSendFromISR(printQueue, &tmp, &woken);
          if (woken) portYIELD_FROM_ISR();
        }
      }
      offset += len + 2;
    }
  }
   if (!matched) track_rf_sighting(&payload[10], packet->rx_ctrl.rssi);
}

// =============================================================================
// JSON Builder (shared format for USB + mesh, includes node_id)
// =============================================================================
static int buildJson(char *buf, size_t bufSize, const uav_data *UAV) {
  char mac_str[18];
  snprintf(mac_str, sizeof(mac_str), "%02x:%02x:%02x:%02x:%02x:%02x",
           UAV->mac[0], UAV->mac[1], UAV->mac[2],
           UAV->mac[3], UAV->mac[4], UAV->mac[5]);

  return snprintf(buf, bufSize,
    "{\"mac\":\"%s\",\"rssi\":%d,\"drone_lat\":%.6f,\"drone_long\":%.6f,"
    "\"drone_altitude\":%d,\"pilot_lat\":%.6f,\"pilot_long\":%.6f,"
    "\"basic_id\":\"%s\",\"node_id\":\"%s\"}",
    mac_str, UAV->rssi, UAV->lat_d, UAV->long_d, UAV->altitude_msl,
    UAV->base_lat_d, UAV->base_long_d, UAV->uav_id, nodeId);
}

// =============================================================================
// JSON Output - Sends to USB Serial + UART (Heltec V3 mesh)
// =============================================================================
static void send_json(const uav_data *UAV) {
  char json[300];
  buildJson(json, sizeof(json), UAV);

  // USB Serial (local monitoring / direct connection to mesh-mapper.py)
  Serial.println(json);

  // LED flash on detection (quick blink)
  digitalWrite(LED_PIN, LOW);   // ON (inverted)
}

// Send to Heltec V3 over UART as fast as possible - let Meshtastic
// handle its own queuing and channel throttling, we don't rate-limit here.
static void send_to_mesh(const uav_data *UAV) {
  char json[300];
  int len = buildJson(json, sizeof(json), UAV);

  if (Serial1.availableForWrite() >= len) {
    Serial1.println(json);
  }
}

// =============================================================================
// FreeRTOS Tasks
// =============================================================================

// Printer task: dequeues UAV data and outputs JSON (runs on core 1)
static void printerTask(void *param) {
  uav_data UAV;
  rf_candidate_msg rf;
  for (;;) {
    if (xQueueReceive(printQueue, &UAV, pdMS_TO_TICKS(50))) {
      send_json(&UAV);
      send_to_mesh(&UAV);
    }
    while (xQueueReceive(rfQueue, &rf, 0)) {
      char mac_str[18];
      snprintf(mac_str, sizeof(mac_str), "%02x:%02x:%02x:%02x:%02x:%02x",
               rf.mac[0], rf.mac[1], rf.mac[2], rf.mac[3], rf.mac[4], rf.mac[5]);
      Serial.printf("{\"type\":\"rf_candidate\",\"mac\":\"%s\",\"rssi\":%d}\n",
                    mac_str, rf.rssi);
    }
  }
}

// BLE scan task (runs on core 1)
static void bleScanTask(void *param) {
  for (;;) {
    BLEScanResults results = pBLEScan->start(1, false);
    pBLEScan->clearResults();
    delay(100);
  }
}

// WiFi processing task - just keeps the task alive (runs on core 0)
static void wifiProcessTask(void *param) {
  for (;;) {
    delay(10);
  }
}

// UART forward task: anything the Heltec sends back gets echoed to USB
// (mesh acknowledgments, Meshtastic debug output, etc.)
static void uartForwardTask(void *param) {
  static char lineBuf[512];
  static int linePos = 0;

  for (;;) {
    while (Serial1.available()) {
      char c = Serial1.read();
      if (c == '\n' || c == '\r') {
        if (linePos > 0) {
          lineBuf[linePos] = '\0';
          Serial.println(lineBuf);
          linePos = 0;
        }
      } else if (linePos < (int)sizeof(lineBuf) - 1) {
        lineBuf[linePos++] = c;
      }
    }
    delay(10);
  }
}

// =============================================================================
// Arduino Entry Points
// =============================================================================
void setup() {
  delay(3000);  // Boot delay (Meshtastic serial init timing)
  setCpuFrequencyMhz(160);

  // Generate unique node ID from ESP32 factory MAC
  generateNodeId();

  // Serial init
  Serial.begin(115200);
  Serial1.begin(115200, SERIAL_8N1, SERIAL1_RX_PIN, SERIAL1_TX_PIN);

  // LED init
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);  // OFF (inverted logic on XIAO)

  Serial.println();
  Serial.println("================================================");
  Serial.println("  DRONE MESH MAPPER - REMOTE NODE");
  Serial.printf("  Node ID: %s\n", nodeId);
  Serial.println("  WiFi + BLE Remote ID Detection");
  Serial.println("  UART -> Heltec V3 Meshtastic Mesh");
  Serial.println("================================================");

  nvs_flash_init();

  // WiFi promiscuous mode for ODID NAN/Beacon frames
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&callback);
  esp_wifi_set_channel(6, WIFI_SECOND_CHAN_NONE);
  Serial.println("[REMOTE] WiFi promiscuous mode active (ch6)");

  // BLE scanner for ODID BLE advertisements
  BLEDevice::init("DroneID");
  pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new DroneIDCallback());
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);
  Serial.println("[REMOTE] BLE scanner active");

  // Print queue (ISR-safe bridge between callbacks and printer task)
  printQueue = xQueueCreate(MAX_UAVS * 2, sizeof(uav_data));
  rfQueue = xQueueCreate(16, sizeof(rf_candidate_msg));
  memset(sightings, 0, sizeof(sightings));

  // Clear tracking array
  memset(uavs, 0, sizeof(uavs));

  // Launch FreeRTOS tasks on separate cores
  xTaskCreatePinnedToCore(bleScanTask,     "BLE",     10000, NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(wifiProcessTask, "WiFi",    10000, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(printerTask,     "Print",   10000, NULL, 1, NULL, 1);
  xTaskCreatePinnedToCore(uartForwardTask, "UART_FW",  4096, NULL, 1, NULL, 1);

  Serial.println("[REMOTE] All tasks launched - scanning for drones...\n");
}

void loop() {
  unsigned long now = millis();

  // Heartbeat every 60 seconds
  if (now - last_status > 60000UL) {
    Serial.println("{\"heartbeat\":\"remote_node active\"}");
    last_status = now;
  }

  // LED off after brief flash (set ON by send_json)
  static unsigned long ledOffTime = 0;
  static bool ledOn = false;
  if (digitalRead(LED_PIN) == LOW) {
    if (!ledOn) { ledOn = true; ledOffTime = now; }
    if (now - ledOffTime > 80) {
      digitalWrite(LED_PIN, HIGH);  // OFF
      ledOn = false;
    }
  }

  delay(10);
}
