# CareBridge – Maternal Telemedicine Dashboard

CareBridge is a Raspberry Pi–based maternal telemedicine dashboard integrated into a tricycle platform to improve access to emergency and remote healthcare services. The system enables real-time communication between patients and healthcare providers using GSM voice calls, SMS messaging, and video consultations through a screen-based interface.

Designed for use in underserved and rural communities, CareBridge allows a medical emergency to be reported instantly through a single button press, connecting the patient to the nearest healthcare facility or national emergency response center.


## 🩺 Project Overview

Maternal healthcare emergencies often require rapid response and immediate medical guidance. CareBridge addresses this challenge by combining embedded systems, telecommunication technologies, and telemedicine into a mobile healthcare solution.

The system is mounted on a tricycle and operates as a mobile telemedicine unit, enabling communication with healthcare personnel while transporting patients to medical facilities.


## 🚀 Features

- **One-Button Emergency Alert**
  - Instantly notifies the nearest healthcare center
  - Can call the national emergency service line

- **GSM Voice Communication**
  - Place and receive calls directly from the dashboard
  - Reliable communication in low-internet areas

- **SMS Messaging**
  - Send text alerts and emergency notifications

- **Remote Video Consultation**
  - Real-time video calls with healthcare personnel
  - Enables remote medical guidance during transport

- **Embedded Dashboard Interface**
  - Screen-based interaction powered by Raspberry Pi
  - Simple and user-friendly design


## 🧰 Hardware Components

- Raspberry Pi
- LCD / Touch Screen Display
- GSM Module
- Camera and Microphone
- Emergency Push Button
- CareBridge Tricycle Platform


## 🛠️ Software & Technologies

- Python
- Raspberry Pi OS (Linux)
- GSM / UART Serial Communication
- Video Communication Stack
- Embedded Systems & IoT


## 📐 System Architecture

1. User presses the emergency button  
2. Raspberry Pi triggers GSM communication  
3. Emergency call or SMS is sent to healthcare center  
4. Video consultation is initiated via the dashboard screen  
5. Healthcare personnel provide real-time guidance  


## ⚙️ Setup & Configuration

1. Install Raspberry Pi OS on the Raspberry Pi
2. Enable serial communication using `raspi-config`
3. Connect the GSM module via UART
4. Attach the screen, camera, microphone, and emergency button
5. Install required Python dependencies
6. Run the main application script

```bash
python3 careBridgeworking1.py
