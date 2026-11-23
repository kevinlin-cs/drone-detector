# Third-party notices

This repository combines my original code with code from other open-source projects. Each part stays under its own license, as described below. The `LICENSE` file at the top level applies only to my original work (see "My work" at the end).

---

## 1. Node-mode firmware: colonelpanichacks/drone-mesh-mapper (MIT)

Files: `firmware/src/main_remote.cpp`, `firmware/src/main_home.cpp`, `firmware/src/main.cpp`, `firmware/platformio.ini` (derived from the node-mode firmware in https://github.com/colonelpanichacks/drone-mesh-mapper).

`main_remote.cpp` and `main.cpp` are modified by me; `main_home.cpp` is unmodified. The `platformio.ini` change is one line (excluding `main.cpp` from the build).

The upstream license notice follows, as required:

```
MIT License

Copyright (c) 2025-2026 colonelpanichacks

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Upstream lineage

According to the upstream project's own README, its firmware descends from Remote ID work by **Cemaxecuter** and **alphafox02**, and it began as a fork of [JimZGChow/wifi-rid-to-mesh](https://github.com/JimZGChow/wifi-rid-to-mesh), which publishes no license. Code that originates there remains under its author's terms.

---

## 2. Open Drone ID core library (Apache-2.0)

Files, unmodified: `firmware/src/opendroneid.c`, `firmware/src/opendroneid.h`, `firmware/src/odid_wifi.h`, `firmware/src/wifi.c`.

- Copyright (C) 2019 Intel Corporation (`opendroneid.*`, `odid_wifi.h`)
- Copyright (C) 2020 Simon Wunderlich, Marek Sobe and Doodle Labs (`wifi.c`)
- Licensed under the Apache License, Version 2.0. The license headers in each file are kept as they are, and the full license text is in [LICENSE-APACHE-2.0](LICENSE-APACHE-2.0).
- Source: https://github.com/opendroneid/opendroneid-core-c

---

## 3. My work

Copyright (c) 2026 Kevin Lin, released under the MIT License (see `LICENSE`):

- `backend/dronepi_backend.py` (backend, dashboard and demo generator)
- `systemd/dronepi.service`
- The RF-candidate detector added to `firmware/src/main_remote.cpp` (the `rf_sighting` structures, `find_or_create_sighting`, `record_and_classify`, `track_rf_sighting`, and their hooks into the callbacks and output queue)
- This README and documentation
