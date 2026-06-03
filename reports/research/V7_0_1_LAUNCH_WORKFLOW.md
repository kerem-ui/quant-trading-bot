# V7.0.1 — Launch / Mobile Access Workflow

_Operator-facing how-to for launching the V7 platform locally and, optionally, viewing it from a phone or tablet on the same Wi-Fi. Documentation milestone — no new functionality, no new dependencies._

**Status: documentation + optional launch-helper PowerShell scripts.** The platform itself is unchanged. `LIVE_TRADING_ENABLED` remains `False`. No broker, no IBKR, no live data fetch, no internet exposure.

---

## 1. Normal local launch (recommended default)

This is the safest and intended day-to-day workflow. The platform binds only to `127.0.0.1` and is reachable only from the machine it runs on.

```
python -m streamlit run apps/portfolio_platform.py
```

Streamlit prints a URL like:

```
  Local URL: http://localhost:8501
  Network URL: http://127.0.0.1:8501
```

Open the **Local URL** in your browser. Done.

### Stopping the platform

Press **`Ctrl+C`** in the terminal running streamlit. The platform shuts down cleanly. No background processes survive.

### Why localhost is the default

- No other machine on your network can reach the dashboard.
- No router / firewall configuration is needed.
- No security caveats apply.
- Read-only research data still cannot leak.

---

## 2. Existing V6 sector dashboard launch

The original V6.5.x sector dashboard remains available alongside the V7 platform. It is a separate Streamlit app and runs on a different port if the platform is also running.

```
python -m streamlit run apps/sector_thesis_dashboard.py
```

Same `Ctrl+C` to stop. Same localhost-only default.

You can run both simultaneously — streamlit picks a fresh port (typically `8501`, then `8502`) for the second one. The two apps share the same on-disk CSVs; neither writes to them.

---

## 3. Phone / tablet access on the same Wi-Fi (LAN-only)

**Use this only on a trusted home or office Wi-Fi network you control.** If you are on hotel / café / airport / shared / public Wi-Fi, do not use this mode — it makes the dashboard reachable from every device on the same network.

### Step 1 — start streamlit bound to the LAN

```
python -m streamlit run apps/portfolio_platform.py --server.address 0.0.0.0
```

`--server.address 0.0.0.0` tells streamlit to listen on every network interface, including your LAN IP. **This is opt-in only.** Streamlit's default (with no `--server.address` flag) is localhost.

### Step 2 — find your PC's LAN IP

On Windows, in a separate terminal:

```
ipconfig
```

Look for the `IPv4 Address` line under your active Wi-Fi adapter, e.g.:

```
Wireless LAN adapter Wi-Fi:
   IPv4 Address. . . . . . . . . . . : 192.168.1.42
```

That number (`192.168.1.42` in the example) is your PC's LAN IP.

### Step 3 — open the dashboard on the phone

On the phone or tablet, connected to the **same Wi-Fi** as the PC, open a browser and visit:

```
http://<PC-LAN-IP>:8501
```

Example: `http://192.168.1.42:8501`

The platform should render. You can navigate every page exactly as you would on the PC.

### Step 4 — shut down

Press **`Ctrl+C`** in the terminal on the PC running streamlit. The LAN-bound session ends. The phone's browser will show a connection-failed page on the next page-load, which is the expected, safe outcome.

---

## 4. Security caveats (read before using LAN mode)

LAN mode is the only mode in this document where security caveats apply. Read all of them before running streamlit with `--server.address 0.0.0.0`.

### What LAN mode actually does

- It tells streamlit to accept connections from any device on every network interface, not just localhost.
- Anyone connected to the same Wi-Fi network as the PC can reach the dashboard at `http://<PC-LAN-IP>:8501`.
- That includes guests on your home Wi-Fi, anyone on a shared office network, and (critically) every other device on hotel / café / airport / public Wi-Fi.

### Hard rules

- **LAN-only.** Use only on a Wi-Fi network you trust and control. Home Wi-Fi with WPA2/WPA3 and no untrusted guests is OK. Public Wi-Fi is never OK.
- **Do not use on public or untrusted Wi-Fi.** Coffee shops, hotels, airports, conferences, shared apartments where you don't control the router — all out of scope.
- **Anyone on the same LAN may be able to view the dashboard.** The platform is read-only, so the worst case is data exposure (positions, sector signals, P&L), not data corruption. But data exposure is real — assume any device on the same LAN can see everything the platform shows.
- **Do not configure router port forwarding.** Port forwarding would expose the dashboard to the public internet. The platform is not designed for internet exposure and has no authentication.
- **Do not expose this to the internet.** No port forwarding, no NAT punching, no reverse proxy, no Tailscale / Cloudflare Tunnel / ngrok bridging without the security understanding to do so safely. If you don't already know how to deploy a read-only research app behind authentication, you should not be exposing this one to the internet.
- **No authentication is added in V7.0.1.** Streamlit accepts every connection. There is no login screen, no password, no API key, no IP allowlist. Adding authentication is a future, explicit milestone (not currently planned).
- **The platform is read-only and has no order execution.** This stays true in LAN mode — the worst case remains data exposure, not data corruption or unauthorised trading. But data privacy still matters.
- **Shut down with `Ctrl+C` when finished.** Don't leave a LAN-bound session running unattended. As soon as you stop using the phone view, stop streamlit.

### Optional firewall / router-side hardening

If you want belt-and-braces protection on your home network:

- Use the Windows Firewall to restrict port 8501 inbound to your private LAN subnet only (typically `192.168.0.0/16` or `10.0.0.0/8`). Default Windows behaviour for streamlit will prompt you to allow / deny on first launch — choose **Private networks** and **deny Public networks**.
- Disable Wi-Fi guest network access while running LAN mode, or move guest devices off the main SSID.
- Consider running LAN mode only ad-hoc for short sessions rather than leaving it always-on.

These are operator-side hardening steps — none of them are required for the platform to function, but they reduce the LAN attack surface to the smallest practical set of devices.

---

## 5. One-click / direct open convenience

V7.0.1 ships two small PowerShell launcher scripts. They are thin wrappers around the `python -m streamlit run …` commands above. They exist so the operator can double-click or shortcut-launch without remembering the full command.

### `scripts/launch_platform.ps1`

Launches the V7 platform. Localhost-only by default.

```
.\scripts\launch_platform.ps1
```

To opt into LAN mode (only on a trusted Wi-Fi):

```
.\scripts\launch_platform.ps1 -Lan
```

The `-Lan` switch:

- Binds streamlit to `0.0.0.0` (every interface).
- Prints the LAN security caveats from §4 to the console **before** starting streamlit.
- Requires the operator to acknowledge by pressing any key. Without that acknowledgement the script exits without starting streamlit.

Without `-Lan`, the script binds to `127.0.0.1` and starts streamlit immediately with no warning prompt.

### `scripts/launch_sector_dashboard.ps1`

Same shape, for the V6 sector dashboard:

```
.\scripts\launch_sector_dashboard.ps1
.\scripts\launch_sector_dashboard.ps1 -Lan
```

### What the launcher scripts do NOT do

- They do not fetch any data. No FRED calls, no yfinance, no IBKR, no ThetaData, no news scraping.
- They do not write to any CSV. The V6/V7 artefacts are read-only from the launcher's perspective.
- They do not modify any setting on disk.
- They do not install any package. If `streamlit` is not on the PATH, the script prints a friendly error and exits.
- They do not start any IBKR session. No `ib_insync`, no `ibapi`, no TWS/Gateway contact.
- They do not expose the dashboard to the LAN unless `-Lan` is passed.
- They do not store credentials or secrets.
- They do not run any trading or order code.

The launcher scripts are pure convenience wrappers around the documented `streamlit run` commands.

---

## 6. Where this fits in the project

- **`README.md`** at the repo root briefly mentions this workflow document. Run the platform with the existing commands; this doc is the place to go when you want to know how phone access or `-Lan` mode works.
- The V7.2 IBKR design (`V7_2_IBKR_READONLY_DESIGN.md`) is a separate, deferred milestone. V7.0.1 does not unlock or enable V7.2. V7.0.1 is purely about launching what's already built.
- The V6.5.x sector dashboard (`apps/sector_thesis_dashboard.py`) is byte-identical to its V6 form. The V7 platform (`apps/portfolio_platform.py`) is byte-identical to its V7.4 form. Nothing has been touched.

### Future milestones that could build on V7.0.1

- **V7.0.2 (low priority)** — bash equivalents of the PowerShell launchers for operators on macOS / Linux. Same shape; same security caveats; not currently needed because the project is operated on Windows.
- **V7.5 Company Detail / Stock Intelligence page** — recommended next research milestone. A read-only page that drills into a single ticker by joining V6.7 ledger, V6.8 aggregation, V7.1 position (if held), V7.7 protection label, and V7.4 PortTech label. Mirrors the categorical, pre-declared, no-network shape of every V7 page so far.

V7.5 is the right next research milestone after V7.0.1. V7.2 implementation remains deferred per the V7.2 design's §10 path-recommendation.

---

## Quick reference card

| Action | Command |
|---|---|
| Launch platform (localhost) | `python -m streamlit run apps/portfolio_platform.py` |
| Launch sector dashboard (localhost) | `python -m streamlit run apps/sector_thesis_dashboard.py` |
| Launch platform (LAN, trusted Wi-Fi only) | `python -m streamlit run apps/portfolio_platform.py --server.address 0.0.0.0` |
| Find PC LAN IP (Windows) | `ipconfig` |
| Phone URL (LAN mode) | `http://<PC-LAN-IP>:8501` |
| Shut down | `Ctrl+C` in the streamlit terminal |
| Launch script (localhost) | `.\scripts\launch_platform.ps1` |
| Launch script (LAN, with prompt) | `.\scripts\launch_platform.ps1 -Lan` |

---

**This workflow assumes a trusted local network. The platform is read-only research software with no authentication and no order execution. Do not configure router port forwarding. Do not expose this to the public internet. Use `Ctrl+C` to shut down when you are done.**
