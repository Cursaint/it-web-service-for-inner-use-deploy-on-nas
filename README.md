# IT Service & Asset Management System

A modern, lightweight IT Helpdesk and Asset Management web application built with **FastAPI**, **Jinja2**, and **PostgreSQL**.

---

## 🌟 Features

- **IT Service Desk / Ticketing:**
  - Submit IT requests and issues with urgency levels, category, and requester details.
  - Track ticket status, assigned technician, work notes, and resolutions.
  - Interactive ticket report and detail view.

- **IT Asset Management:**
  - Register and manage company hardware assets (PCs, laptops, monitors, printers, networking equipment).
  - Component Assembly management (attach/detach RAM, storage, GPU to parent machines).
  - PC Software & Remote Access configuration (OS, IP address, MAC, remote support credentials, email).

- **Real-Time Notifications:**
  - Web in-app notification bell with real-time polling.
  - Background Windows Toast Notifier via PowerShell task scheduler.

- **Fast & Responsive:**
  - Asynchronous endpoints powered by FastAPI.
  - Clean, responsive UI with zero heavy frontend frameworks.

---

## 🛠️ Tech Stack

- **Backend:** FastAPI, Uvicorn, Python 3.11+
- **Database:** PostgreSQL (using `psycopg` and `SQLAlchemy`)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript, Jinja2 Templates
- **Containerization:** Docker & Docker Compose

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11 or higher
- PostgreSQL Database (local or remote/Docker)
- (Optional) Docker and Docker Compose

### 2. Clone the Repository
```bash
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
```

### 3. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` and fill in your database credentials:
```env
PORT=8000
DATABASE_URL=postgresql://<username>:<password>@<host>:<port>/<database_name>
IT_SERVICE_URL=http://localhost:8000
```

> ⚠️ **Important:** Never commit the `.env` file to version control. It is already included in `.gitignore`.

---

## 💻 Running the Application

### Option A: Running with Docker Compose (Recommended)
```bash
docker compose up -d --build
```
Access the application at `http://localhost:8000`.

### Option B: Running Locally with Python
1. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the development server:**
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

---

## 🔔 Windows Desktop Ticket Notifier (Optional)

The `tools/` folder contains a Windows background service that polls for new tickets and displays native Windows Toast Notifications:

To install as a Windows Scheduled Task (runs automatically at sign-in):
```powershell
powershell -ExecutionPolicy Bypass -File tools\install_ticket_notifier.ps1 -SiteUrl "http://localhost:8000"
```

---

## 📁 Project Structure

```text
├── database.py                 # Database engine and connection helpers
├── main.py                     # FastAPI application entrypoint
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container build instructions
├── docker-compose.yml          # Container orchestration
├── .env.example                # Sample environment configuration
├── .gitignore                  # Git ignore rules for sensitive files
├── routes/
│   ├── get.py                  # Page rendering and GET API endpoints
│   └── post.py                 # Form actions and POST API endpoints
├── template/                   # Jinja2 HTML templates
│   ├── home.html
│   ├── it_request.html
│   ├── my_tickets.html
│   ├── ticket_report.html
│   ├── assets.html
│   ├── asset_new.html
│   ├── asset_assembly.html
│   └── asset_software.html
├── static/                     # CSS stylesheets and client scripts
│   ├── style.css
│   ├── script.js
│   └── notifications.js
└── tools/                      # Windows desktop notification helper scripts
    ├── ticket_notifier.py
    ├── show_ticket_toast.ps1
    └── install_ticket_notifier.ps1
```

---

## 🛡️ Security & Privacy Notice
All sensitive database credentials, network IP addresses, and private configurations have been decoupled into `.env`. Ensure your production deployment sets strong database passwords and restricts database access.

---

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.
