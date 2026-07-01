# AIOps-Driven Cloud Resource Management System on OpenNebula

An intelligent cloud resource management system built on OpenNebula, integrating an AI Agent (CrewAI + Groq API) following the MAPE-K autonomic computing model, a Prometheus/Grafana/Alertmanager monitoring stack, and an MCP-based infrastructure control layer. The system continuously monitors cloud resources, analyzes anomalies, and provides remediation recommendations through a web-based dashboard.

## Overview

This project was developed as a **major/specialized capstone project (Đồ án chuyên ngành)** at the **University of Information Technology (UIT - VNU-HCM)**, Faculty of Computer Networks and Communications.

The system combines Cloud Computing, AIOps, and Multi-Agent AI technologies to create a self-monitoring, self-analyzing cloud resource management platform for Infrastructure-as-a-Service (IaaS) environments.

**Title (VN):** Thiết kế và triển khai hệ thống quản lý tài nguyên Cloud sử dụng AI Agent trên nền tảng OpenNebula

**Title (EN):** Design and Implement an AI Agent-based Cloud Resource Management System on the OpenNebula Platform

## Features

* Real-time monitoring of CPU, RAM, Disk, and Network resources
* OpenNebula cloud infrastructure management (KVM hypervisor)
* Prometheus-based metrics collection with Alertmanager alerting
* Grafana dashboard visualization, embedded directly into the web app
* AI-powered anomaly analysis and remediation planning using CrewAI + Groq API (Llama 3.3 70B)
* MCP Server (FastMCP) integration for sandboxed, tool-based infrastructure interaction
* Human-in-the-Loop approval workflow, with an optional Autonomous mode
* AI Chatbox for administrator interaction with the agent
* Incident logging, audit trail, and demo incident exports
* Web-based management dashboard (Dashboard / AI Agent / System Logs)

---

## System Architecture

```text
OpenNebula Host
      │
Node Exporter
      │
Prometheus ── Alertmanager
      │
      ├── Grafana Dashboard
      │
      └── CrewAI + Groq API (MAPE-K Agent)
                │
           MCP Server (FastMCP)
                │
           OpenNebula API
                │
         FastAPI Backend
                │
           Web Dashboard
```

---

## Technologies Used

### Cloud Infrastructure
* OpenNebula
* KVM Hypervisor
* Ubuntu Server 20.04 LTS

### Monitoring
* Prometheus
* Node Exporter
* Alertmanager
* Grafana

### Artificial Intelligence
* CrewAI
* Groq API
* Llama 3.3 70B
* MCP (Model Context Protocol) / FastMCP

### Backend
* FastAPI
* Uvicorn
* Pydantic
* HTTPX
* SQLite (aiosqlite)
* ChromaDB

### Frontend
* HTML5
* Vanilla JavaScript
* Tailwind CSS
* Material Symbols

---

## Deployment Environment

### Controller Node (Front-end)

| Component            | Description                  |
| --------------------- | ----------------------------- |
| OpenNebula Frontend   | Cloud management platform     |
| Prometheus            | Monitoring server             |
| Alertmanager          | Alert routing                 |
| Grafana               | Visualization dashboard       |
| FastAPI               | Backend service                |
| CrewAI                | AI Agent orchestration        |
| MCP Server            | Infrastructure tool gateway   |

**IP Address:** `192.168.57.7`

### Compute Node (Host Node)

| Component         | Description               |
| ------------------ | --------------------------|
| OpenNebula Host    | Resource provider          |
| KVM Hypervisor     | Virtualization platform    |
| Node Exporter      | Metrics collection         |
| Virtual Machines   | Cloud workloads            |

**IP Address:** `192.168.57.9`

---

## Project Structure

```text
NT114/
│
├── backend/
│   ├── __pycache__/
│   ├── api/
│   │   ├── __pycache__/
│   │   ├── agent_api.py         # AI Agent (MAPE-K) endpoints
│   │   └── dashboard_api.py     # Dashboard / metrics endpoints
│   ├── demo_logs/
│   │   └── incident_2026...     # Exported incident logs (JSON)
│   ├── .env                     # Environment variables
│   ├── agent_logs.db            # SQLite log/knowledge store
│   ├── ai_worker.py             # CrewAI worker / MAPE-K loop
│   ├── config.py                # App configuration
│   ├── database.py              # DB access layer
│   ├── main.py                  # FastAPI entrypoint
│   ├── mcp_server.py            # FastMCP server (infrastructure tools)
│   ├── process_tools.py         # Host process inspection / kill tools
│   └── requirements.txt
│
├── frontend/
│   └── templates/
│       ├── ai_agent.html        # AI Agent workflow control page
│       ├── dashboard.html       # System overview dashboard
│       └── system_logs.html     # System logs + AI chatbox page
│
├── monitoring/
│   ├── alertmanager/
│   ├── grafana/
│   └── prometheus/
│
├── scenario/                    # Test scenario scripts (e.g. stress-ng)
├── venv/
├── docker-compose.yml
├── deploy.sh
├── .gitignore
└── README.md
```

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/hoangle795/opennebula-ai-resource-manager.git
cd NT114
```

### 2. Create Virtual Environment

```bash
python -m venv venv

source venv/bin/activate
# Linux

venv\Scripts\activate
# Windows
```

### 3. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `backend/.env` file:

```env
GROQ_API_KEY=your_groq_api_key

PROMETHEUS_URL=http://localhost:9090

OPENNEBULA_URL=http://localhost:2633/RPC2

OPENNEBULA_USERNAME=oneadmin
OPENNEBULA_PASSWORD=password
```

### 5. Start Backend

```bash
uvicorn main:app --reload
```

---

## Running the System

### Start Prometheus / Alertmanager / Grafana

```bash
sudo systemctl start prometheus
sudo systemctl start prometheus-alertmanager
sudo systemctl start grafana-server
```

### Start OpenNebula Services

```bash
sudo systemctl start opennebula
sudo systemctl start opennebula-sunstone
```

### Run AI Agent Backend

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Or, using Docker Compose

```bash
docker-compose up -d
```

---

## MAPE-K Workflow

### Monitor
Prometheus + Node Exporter collect CPU, RAM, Disk, and Network metrics from the Host Node every 15 seconds; Alertmanager triggers the AI Agent when a threshold is violated.

### Analyze
The Monitor Agent queries Prometheus via the MCP Server; Groq API evaluates trends and severity of the current resource state.

### Plan
CrewAI's Analyst Agent generates a structured remediation plan (JSON) with prioritized actions and a natural-language explanation.

### Execute
After administrator approval (or automatically in Autonomous mode), the Reporter Agent executes the plan through MCP tools against OpenNebula/the host, and logs the results.

### Knowledge
Incidents, plans, and execution results are stored in SQLite/ChromaDB and referenced by subsequent MAPE-K cycles.

---

## Web Dashboard

The management dashboard includes three pages:

* **Dashboard** — infrastructure overview, real-time metrics, critical alerts, host node status, embedded Grafana panels
* **AI Agent** — MAPE-K phase tracking, analysis results, remediation proposals, Approve/Reject controls, Autonomous mode toggle
* **System Logs** — live telemetry stream and AI Chatbox for querying system health and issuing remediation commands

---

## Future Improvements

* Multi-host OpenNebula cluster and larger-scale evaluation
* Increased automation (live migration, VM provisioning, cluster scaling) within safe boundaries
* Predictive resource allocation using machine learning
* Local/small LLM deployment to reduce third-party API dependency
* RAG-based knowledge base using ChromaDB embeddings
* RBAC, JWT/OAuth2 authentication, and encrypted internal communication

---

## Authors

| Name             | Student ID |
| ---------------- | ---------- |
| Lê Xuân Hoàng     | 23520524   |
| Đặng Minh Dzũ     | 23520404   |

**Advisor:** ThS. Trần Thị Dung

---

## Project Information

* Specialized/Major Capstone Project (Đồ án chuyên ngành)
* University of Information Technology (UIT - VNU-HCM)
* Faculty of Computer Networks and Communications
* Ho Chi Minh City, 2026

---

## License

This project is developed for educational and research purposes.