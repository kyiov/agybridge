<p align="center">
  <img src="docs/logo.png" width="96" height="96" alt="AGYBridge Logo" />
</p>

<h1 align="center">AGYBridge Gateway</h1>

<p align="center">
  <strong>Gateway Proksi Berperforma Tinggi untuk Google Antigravity</strong><br>
  <em>Menjembatani Google Antigravity ke dalam antarmuka standar OpenAI, Anthropic Claude, dan Google Gemini API.</em>
</p>

<p align="center">
  <a href="#-fitur-utama"><img src="https://img.shields.io/badge/Python-3.12+-blue.svg?style=flat-square" alt="Python" /></a>
  <a href="#-fitur-utama"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat-square" alt="FastAPI" /></a>
  <a href="#-fitur-utama"><img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License" /></a>
  <a href="#-fitur-utama"><img src="https://img.shields.io/badge/Status-Active-brightgreen.svg?style=flat-square" alt="Status" /></a>
</p>

---

## 🌟 Fitur Utama

- **Kompatibilitas Tiga Format Standar:**
  - **OpenAI Endpoint:** `/v1/chat/completions` dan `/v1/models` (kompatibel penuh dengan pustaka OpenAI SDK, LangChain, NextChat, LobeChat, Chatbox, dll.).
  - **Claude Endpoint:** `/v1/messages` dan `/v1/messages/count_tokens` (kompatibel dengan Anthropic SDK & Claude Dev).
  - **Gemini Native Endpoint:** `/v1/models/{model}:generateContent` dan `streamGenerateContent`.
- **Manajemen Multi-Akun Otomatis:**
  - Rotasi kredensial otomatis dengan pemisahan beban merata (*load balancing*).
  - Pengenalan otomatis tingkat langganan akun (*Free*, *Pro*, *Ultra*) serta *Project ID*.
  - Isolasi cooldown tingkat model saat menemui limit HTTP 429 tanpa mematikan akun secara global.
- **Optimasi Prompt Cache:**
  - Mode pemilihan kredensial berbasis hash konteks (`cache`) untuk memaksimalkan *prompt caching* upstream Google, memangkas latensi, dan menghemat konsumsi token.
- **Anti-Pemotongan Respons (Anti-Truncation):**
  - Mencegah jawaban terpotong pada respons teks panjang dengan mekanisme auto-continue berbasis prefix `anti-truncate-`.
- **Panel Web Terintegrasi:**
  - Antarmuka manajemen lengkap (React + Tailwind + Inter/JetBrains Mono typography) untuk memantau status akun, sisa kuota, log permintaan rinci, dan konfigurasi sistem tanpa restart.
- **Dukungan Streaming SSE:**
  - Pengiriman respons streaming *real-time* (Server-Sent Events) dengan pemisahan token penalaran (*reasoning / thinking tokens*).

---

## 🚀 Panduan Instalasi & Menjalankan

### Kebutuhan Sistem
- Linux / macOS / Windows WSL
- Python 3.12 atau versi lebih baru
- Pengelola paket `uv` (sangat direkomendasikan) atau `pip`
- `bun` (digunakan untuk kompilasi frontend)

### 1. Kloning Repositori & Persiapan Lingkungan

```bash
# Kloning repositori
git clone https://github.com/your-username/agybridge.git agybridge
cd agybridge

# Buat virtual environment dengan uv
uv venv
source .venv/bin/activate

# Pasang dependensi
uv sync
```

### 2. Konfigurasi Lingkungan (`.env`)

Salin berkas contoh atau buat berkas `.env` di direktori utama:

```env
# Port dan Host Layanan
PORT=7861
HOST=0.0.0.0

# Keamanan Akses
PANEL_PASSWORD=kata_sandi_panel_anda
API_PASSWORD=kunci_akses_api_anda

# Pemilihan Kredensial (cache / random / sticky)
CREDENTIAL_SELECT_MODE=cache

# Log Permintaan
USAGE_LOG_ENABLED=true
REQUEST_LOG_ENABLED=false
```

### 3. Menjalankan Layanan

#### Mode Langsung (Development)
```bash
source .venv/bin/activate
python web.py
```

#### Mode Background dengan PM2 (Produksi)
```bash
# Menjalankan backend dengan PM2
pm2 start /root/agybridge/.venv/bin/python3 --name "agybridge" -- web.py

# Menyimpan konfigurasi agar aktif saat server reboot
pm2 save
```

---

## 🔒 Akses Jaringan & Tunneling

Layanan berjalan pada port internal `7861`. Untuk mengakses panel dan API secara aman dari luar:

### Opsi A: SSH Local Port Forwarding (Paling Privat)
Akses langsung melalui jalur terenkripsi SSH tanpa membuka port publik:
```bash
ssh -L 7861:localhost:7861 user@ip_server_anda
```
Buka peramban di laptop Anda: `http://localhost:7861`

### Opsi B: Cloudflare Tunnel (Akses Remote Aman)
Gunakan Cloudflare Tunnel untuk mengekspos endpoint melalui HTTPS tanpa perlu membuka port firewall:
```bash
cloudflared tunnel --url http://127.0.0.1:7861
```

---

## 📡 Contoh Penggunaan API

Gunakan kunci API yang Anda tentukan pada parameter `API_PASSWORD`.

### 1. Format OpenAI (`/v1/chat/completions`)

```bash
curl -X POST "http://localhost:7861/v1/chat/completions" \
  -H "Authorization: Bearer kata_sandi_api_anda" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini-3.8-flash-high",
    "messages": [
      {"role": "user", "content": "Halo, jelaskan konsep dasar microservices secara ringkas."}
    ],
    "stream": false
  }'
```

### 2. Format Anthropic Claude (`/v1/messages`)

```bash
curl -X POST "http://localhost:7861/v1/messages" \
  -H "x-api-key: kata_sandi_api_anda" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-4-5",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Analisis efisiensi algoritma quicksort."}
    ]
  }'
```

### 3. Integrasi Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="kata_sandi_api_anda",
    base_url="http://localhost:7861/v1"
)

response = client.chat.completions.create(
    model="gemini-3.8-flash-high",
    messages=[
        {"role": "user", "content": "Tuliskan fungsi Python untuk binary search."}
    ]
)

print(response.choices[0].message.content)
```

---

## ⚙️ Variabel Konfigurasi Utama

| Variabel | Deskripsi | Standar |
| :--- | :--- | :--- |
| `PORT` | Port server HTTP yang didengarkan | `7861` |
| `HOST` | Alamat IP binding host | `0.0.0.0` |
| `PANEL_PASSWORD` | Kata sandi untuk login ke panel kontrol web | `pwd` |
| `API_PASSWORD` | Token otorisasi Bearer untuk pemanggilan API | `pwd` |
| `CREDENTIAL_SELECT_MODE` | Strategi rotasi akun (`random`, `cache`, `sticky`) | `cache` |
| `AUTO_BAN` | Menonaktifkan otomatis kredensial yang error 403 | `false` |
| `RETRY_429_ENABLED` | Mencoba ulang otomatis saat menemui limit 429 | `true` |
| `RETURN_THOUGHTS_TO_FRONTEND` | Menyertakan reasoning/thinking token dalam output | `true` |
| `USAGE_LOG_ENABLED` | Mengaktifkan pencatatan riwayat request ke database | `true` |

---

## 💻 Pengembangan Antarmuka (Frontend)

Antarmuka web dibangun menggunakan **React**, **Vite**, dan **Tailwind CSS** dengan font **Inter** & **JetBrains Mono**:

```bash
cd frontend

# Pasang dependensi
bun install

# Menjalankan mode development
bun run dev

# Membangun aset produksi (disimpan ke direktori dist/)
bun run build
```

Backend secara otomatis menyajikan berkas hasil kompilasi dari direktori `dist/` tanpa membutuhkan server Node.js terpisah saat produksi.

---

## 📜 Lisensi & Catatan

Didistribusikan di bawah lisensi [MIT](LICENSE) © 2026 AGYBridge Contributors.

Proyek ini dibuat untuk tujuan riset, edukasi, dan eksperimen gateway API. Pastikan mematuhi kebijakan penggunaan wajar dan ketentuan layanan upstream yang bersangkutan.
