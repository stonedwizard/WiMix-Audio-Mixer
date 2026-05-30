<p align="center">
  <img src="assets/banner.png" width="100%">
</p>

<h1 align="center">WiMix Audio Mixer</h1>

<p align="center">
  🎚️ Hardware audio mixer for Windows with real-time per-app volume control  
</p>

<p align="center">
  <b>Control your sound with real knobs. Not sliders.</b>
</p>

---

## 🚀 Overview

**WiMix** is a hardware-based audio mixer for Windows that lets you control application volumes using a physical controller (Arduino-based).

Think of it as:

* 🎛️ A DIY alternative to GoXLR
* 🎚️ A Stream Deck — but for audio
* 🔊 EarTrumpet — but with real knobs

---

## 🔥 Features

* 🎚️ Physical control (knobs, sliders, encoders)
* 🔊 Per-application volume control
* ⚡ Real-time response (low latency)
* 🖥️ Works with any Windows app
* 🔧 Fully configurable mapping system
* 📦 Portable (no install required)

---

## 🎬 Demo

> Add GIF or video here
> (this is VERY important for first impression)

```
assets/demo.gif
```

---

## 🧠 How It Works

WiMix consists of two parts:

### 1. Hardware Controller (Arduino)

* Reads input from knobs / encoders / buttons
* Sends data via USB (Serial)

### 2. PC Controller App

* Receives input from device
* Maps controls to apps/devices
* Controls Windows audio sessions in real time

---

## 📂 Project Structure

```
WiMix/
├── app/
│   ├── WiMixController.exe
│   └── wimix_controller.py
├── firmware/
│   └── WiMix_deep.ino
├── config/
│   ├── config.json
│   └── mapping.json
├── assets/
│   ├── banner.png
│   └── demo.gif
└── README.md
```

---

## 🚀 Getting Started

### 1. Flash firmware

Upload firmware to your Arduino:

```
firmware/WiMix_deep.ino
```

---

### 2. Run the app

```
WiMixController.exe
```

or

```
python wimix_controller.py
```

---

### 3. Configure controls

Edit:

* `mapping.json` → assign knobs to applications
* `config.json` → general settings

---

## ⚙️ Requirements

* Windows 10/11
* Arduino-compatible board
* Python (optional, for source run)

---

## 🖼️ Screenshots

> Add UI + hardware photos here

---

## 🧩 Tech Stack

* Python
* Windows Audio API (via pycaw or similar)
* Arduino (C++)
* Serial communication

---

## 🛣️ Roadmap

* [ ] GUI for mapping (drag & drop)
* [ ] Profiles (gaming / music / streaming)
* [ ] OLED display support
* [ ] MIDI support
* [ ] Plugin system
* [ ] Volume meters
* [ ] Auto app detection

---

## 🤝 Contributing

Contributions are welcome.

If you have ideas, open an issue or submit a pull request.

---

## 📄 License

MIT License
