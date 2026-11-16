# Third-party notices

> Disclaimer: This is an independent personal project. It is not affiliated with, endorsed by, or sponsored by Anduril Industries. Anduril and Lattice are trademarks of Anduril Industries, Inc. This repository does not contain or redistribute the Lattice SDK; it is installed from Anduril's official package registries under Anduril's SDK License Agreement.

> Vessel data provided by aisstream.io. Aircraft data comes from the owner's own ADS-B receiver, decoded with readsb. No live data is stored in or distributed from this repository.

Lattice-COP's own code is licensed under the Apache License 2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). Nothing below is relicensed by it. None of the software or data listed here is copied into this repository. Each item is installed, pulled or received at build time or run time, under its own terms.

Licenses were confirmed from each source repository on 2026-11-14.

| Component | Used for | License or terms | How it is used |
| --- | --- | --- | --- |
| [Lattice SDK for Python](https://pypi.org/project/anduril-lattice-sdk/) (`anduril-lattice-sdk`), Anduril Industries | Publishing entities to Lattice | Anduril Lattice Software Development Kit License Agreement (proprietary) | Installed from PyPI at build time. Never vendored, never redistributed. Images that contain it are never pushed to a registry. |
| [Entity Visualizer sample app](https://github.com/anduril/sample-app-entity-visualizer), Anduril Industries | Local map of entities | Anduril Lattice Software Development Kit License Agreement (proprietary) | Cloned from Anduril's repository at a pinned commit at build time and run unmodified. Its code is not in this repository. |
| [AISStream.io](https://aisstream.io/) | Live AIS vessel data | No published terms or data license | Personal, display-only use with credit: "Vessel data provided by aisstream.io." |
| [readsb](https://github.com/wiedehopf/readsb), Matthias Wirth (wiedehopf) and contributors | ADS-B decoding | GNU General Public License, version 3 or any later version | Runs unmodified in its own container. Not built, changed or redistributed here. |
| [tar1090](https://github.com/wiedehopf/tar1090), Matthias Wirth (wiedehopf) and contributors | Receiver web map | GNU General Public License, version 2 or later | Runs unmodified inside the readsb container. |
| [docker-adsb-ultrafeeder](https://github.com/sdr-enthusiasts/docker-adsb-ultrafeeder), sdr-enthusiasts | Container packaging of readsb and tar1090 | GNU General Public License v3.0 | Upstream image pulled by digest, unmodified. |
| [tar1090-db](https://github.com/wiedehopf/tar1090-db), Matthias Wirth (wiedehopf), built from the aircraft database maintained by [Mictronics](https://github.com/Mictronics/readsb) | Aircraft type, registration, operator and build year | No licence is stated in the repository | Read by readsb from the copy inside the upstream image. Not copied, stored or redistributed here. |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Base map tiles in the visualizer | Open Data Commons Open Database License (ODbL) | © OpenStreetMap contributors. Tiles are loaded by the browser from OpenStreetMap's servers. |
| [Leaflet](https://leafletjs.com/) | Map library in the visualizer | BSD 2-Clause License | Installed by the visualizer's own build. |
| [usbipd-win](https://github.com/dorssel/usbipd-win), Frans van Dorsselaer | Sharing the RTL-SDR into WSL2 | GNU General Public License v3.0 | A host tool the owner installs. Not redistributed. |
| [ADS-B Exchange](https://www.adsbexchange.com/) | Fallback aircraft source, only if enabled | Enthusiast terms via RapidAPI; commercial use needs a written license | Personal, non-commercial use only. No resale or redistribution. |

AIS and ADS-B signals are public radio broadcasts. Data derived from them is treated as personal and is not published.

Python and JavaScript dependencies installed at build time keep their own license files inside the built images.
