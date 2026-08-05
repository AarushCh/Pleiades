# Nimbus RX-500 / RX-900 Router — User Manual (excerpt)

## 1. LED status indicators

| LED     | State           | Meaning                                              |
|---------|-----------------|------------------------------------------------------|
| POWER   | Solid white     | Normal operation                                      |
| POWER   | Solid red       | Hardware fault — unit must be replaced                |
| INTERNET| Solid green     | WAN link up, authenticated                            |
| INTERNET| Blinking green  | Negotiating PPPoE / obtaining IP                      |
| INTERNET| Solid amber     | Physical link up, **authentication failed**           |
| INTERNET| Off             | No physical link — check the fibre/coax cable         |
| WIFI    | Blinking blue   | WPS pairing active (2 minute window)                  |
| LAN 1-4 | Blinking        | Traffic on that port                                  |

**A solid amber INTERNET light almost always means wrong PPPoE credentials.** Re-enter the
username and password from your welcome email under Settings → WAN → PPPoE.

## 2. Factory reset

Two methods:

- **Soft reset (keeps credentials):** press and hold the RESET pinhole for 3 seconds. The router
  reboots and clears the DHCP lease table and DNS cache. Use this first for "no internet" issues.
- **Hard reset (erases everything):** press and hold RESET for 15 seconds until the POWER LED
  blinks red three times. This wipes Wi-Fi SSID, password, PPPoE credentials, port forwards and
  firewall rules. You will need your welcome email to reconfigure.

Do not power off the unit during the 60 seconds after a hard reset — this can corrupt the
firmware partition and requires an RMA.

## 3. Wi-Fi troubleshooting

### Slow speeds on 2.4 GHz
The RX-500 and RX-900 both broadcast a single SSID across 2.4 GHz and 5 GHz (band steering).
If devices stick to 2.4 GHz, disable band steering under Settings → Wireless → Advanced and
create a separate `-5G` SSID.

### Devices disconnect every few minutes
Usually DHCP lease exhaustion. Default lease pool is 50 addresses with a 12 hour lease time.
Settings → LAN → DHCP → increase pool to 100 or reduce lease to 2 hours.

### Cannot see the 5 GHz network
Channels 149-165 (UNII-3) are disabled by default on units shipped in India. Set the channel
manually to 36-48 under Settings → Wireless → 5 GHz → Channel.

## 4. Firmware

Auto-update runs between 03:00 and 05:00 local time on Tuesdays. To update manually:
Settings → System → Firmware → Check Now. The RX-500 is on the `rx5xx` firmware branch and the
RX-900 is on `rx9xx`; images are **not** interchangeable and flashing the wrong image bricks the
unit.

Minimum supported firmware is 4.2.1. Units below 4.2.1 cannot connect to the current
authentication servers and must be updated over LAN using the recovery tool.

## 5. Port forwarding
Settings → Firewall → Port Forwarding → Add Rule. Requires a static or dynamic-DNS enabled plan.
Ports 25, 135-139 and 445 are blocked upstream and cannot be forwarded on residential plans.

## 6. Specifications

| Model  | Wi-Fi     | Max throughput | Ethernet         | Concurrent clients |
|--------|-----------|----------------|------------------|--------------------|
| RX-500 | Wi-Fi 5   | 900 Mbps       | 4 × 1 GbE        | 32                 |
| RX-900 | Wi-Fi 6   | 2400 Mbps      | 3 × 1 GbE + 1 × 2.5 GbE | 128         |
