# AI-Powered Cloud Resource Management System

An intelligent cloud resource management system built on OpenNebula, integrating AI Agents, Prometheus monitoring, and MCP-based infrastructure interaction. The system continuously monitors cloud resources, analyzes anomalies, and provides remediation recommendations through a web-based dashboard.

## Overview

This project was developed as a graduation project at the **University of Information Technology (UIT - VNUHCM)**.

The system combines Cloud Computing, AIOps, and Multi-Agent AI technologies to create a self-monitoring and intelligent resource management platform for Infrastructure-as-a-Service (IaaS) environments.

## Features

* Real-time monitoring of CPU, RAM, Disk, and Network resources
* OpenNebula cloud infrastructure management
* Prometheus-based metrics collection
* Grafana dashboard visualization
* AI-powered anomaly analysis using CrewAI and Groq
* MCP Server integration for infrastructure interaction
* Human-in-the-Loop approval workflow
* AI Chatbox for administrator interaction
* Incident logging and audit trail
* Web-based management dashboard

---

## System Architecture

```text
OpenNebula Host
      │
Node Exporter
      │
Prometheus
      │
      ├── Grafana Dashboard
      │
      └── CrewAI + Groq API
                │
           MCP Server
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
* Grafana

### Artificial Intelligence

* CrewAI
* Groq API
* Llama 3.3 70B
* MCP (Model Context Protocol)

### Backend

* FastAPI
* Uvicorn
* Pydantic
* HTTPX
* SQLite
* ChromaDB

### Frontend

* HTML5
* Vanilla JavaScript
* Tailwind CSS
* Material Symbols

---

## Deployment Environment

### Controller Node

| Component           | Description                 |
| ------------------- | --------------------------- |
| OpenNebula Frontend | Cloud management platform   |
| Prometheus          | Monitoring server           |
| Grafana             | Visualization dashboard     |
| FastAPI             | Backend service             |
| CrewAI              | AI Agent orchestration      |
| MCP Server          | Infrastructure tool gateway |

**IP Address:** `192.168.57.7`

### Compute Node

| Component        | Description             |
| ---------------- | ----------------------- |
| OpenNebula Host  | Resource provider       |
| KVM Hypervisor   | Virtualization platform |
| Node Exporter    | Metrics collection      |
| Virtual Machines | Cloud workloads         |

**IP Address:** `192.168.57.9`

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/hoangle795/opennebula-ai-resource-manager.git
cd opennebula-ai-resource-manager
```

### 2. Create Virtual Environment

```bash
python -m venv .venv

source .venv/bin/activate
# Linux

.venv\Scripts\activate
# Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key

PROMETHEUS_URL=http://localhost:9090

OPENNEBULA_URL=http://localhost:2633/RPC2

OPENNEBULA_USERNAME=oneadmin
OPENNEBULA_PASSWORD=password
```

### 5. Start Backend

```bash
uvicorn app.main:app --reload
```

---

## Running the System

### Start Prometheus

```bash
sudo systemctl start prometheus
```

### Start Grafana

```bash
sudo systemctl start grafana-server
```

### Start OpenNebula Services

```bash
sudo systemctl start opennebula
sudo systemctl start opennebula-sunstone
```

### Run AI Agent Backend

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## MAPE-K Workflow

### Monitor

Collect resource metrics from Node Exporter through Prometheus.

### Analyze

Evaluate resource usage and detect anomalies based on predefined thresholds.

### Plan

CrewAI and Groq generate remediation plans in structured JSON format.

### Execute

Administrators approve suggested actions before execution through MCP tools.

### Knowledge

Store incidents, plans, and execution results for future analysis.

---

## Web Dashboard

The management dashboard includes:

* Infrastructure Overview
* Real-Time Monitoring
* AI Agent Analysis
* System Logs
* AI Chatbox
* Alert Management
* Remediation Approval Workflow

---

## Project Structure

```text
project/
│
├── app/
│   ├── api/
│   ├── services/
│   ├── agents/
│   ├── mcp/
│   └── main.py
│
├── frontend/
│   ├── index.html
│   ├── dashboard.html
│   └── assets/
│
├── prometheus/
│   └── prometheus.yml
│
├── grafana/
│   └── dashboards/
│
├── database/
│   └── system.db
│
├── requirements.txt
└── README.md
```

---

## Future Improvements

* Automatic resource scaling
* Predictive resource allocation
* Kubernetes integration
* Multi-host OpenNebula cluster
* AI-driven self-healing infrastructure
* Advanced anomaly detection models

---

## Author

| Name          | Student ID |
| ------------- | ---------- |
| Lê Xuân Hoàng | 23520524   |

---

## Project Information

* Graduation Project
* University of Information Technology (UIT - VNUHCM)
* Faculty of Computer Networks and Communications

**Title:**
Design and Implementation of an AI-Powered Cloud Resource Management System Using OpenNebula, Prometheus, CrewAI, and MCP

---

## License

This project is developed for educational and research purposes.
