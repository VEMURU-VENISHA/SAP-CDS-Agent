# SAP CDS Intelligence & Automation Platform

> **An AI-powered enterprise platform that accepts natural-language SAP business/data requirements, discovers relevant Core Data Services (CDS) views, tables, and associations in SAP S/4HANA, and recommends: `REUSE` → `EXTEND` → `CREATE`.**

---

## 🎯 Strategic Purpose & Vision

In enterprise SAP S/4HANA transformations, developers and architects frequently duplicate existing data models because discovering standard CDS views (VDM - Virtual Data Model) across thousands of views is notoriously difficult. 

The **SAP CDS Intelligence & Automation Platform** solves this by:
1. Translating natural language business requests into technical entity requirements.
2. Interrogating the SAP Virtual Data Model (VDM: Basic, Composite, Consumption layers) via secure, governed connectors.
3. Formulating a rigorous, deterministic decision:
   - **REUSE:** An existing standard SAP CDS view (e.g., `I_SalesOrderAnalytics`) covers the requirement 100%.
   - **EXTEND:** An existing standard CDS view meets >75% of the requirement and can be extended via CDS View Entity Extension (`EXTEND VIEW ENTITY`) without modifying standard objects.
   - **CREATE:** No standard view provides the foundational model; synthesize a custom CDS View Entity (`Z_...`) following SAP clean-core and naming guidelines.
4. Gating all draft generation, validation, and deployment behind strict **human-in-the-loop governance** and ADT transport mechanisms.

---

## 🔒 Enterprise Guardrails & Safety Architecture

- **Zero Credentials in Code:** No SAP passwords, tokens, or private keys are stored.
- **Strict Connector Abstraction:** Clear separation between platform reasoning and SAP communication protocols (RFC / ADT REST / OData).
- **No Hallucinated SAP Objects:** The system never synthesizes fake tables or imaginary fields as real SAP objects.
- **Mandatory Human-in-the-Loop:** Automated generation never activates objects in SAP DEV without explicit senior developer approval and an assigned Transport Request (TR).

---

## 🏗️ Architecture Overview

```
                         +-----------------------------------+
                         |      Enterprise React Frontend     |
                         |   (Vite, Tailwind, React Flow)    |
                         +-----------------+-----------------+
                                           | HTTP / SSE
                                           v
                         +-----------------------------------+
                         |         FastAPI Backend           |
                         |   (Pydantic, Async Engine, Core)  |
                         +-----------------+-----------------+
                                           |
                +--------------------------+--------------------------+
                |                                                     |
                v                                                     v
+-------------------------------+                     +-------------------------------+
|     LangGraph Multi-Agent     |                     |     SAP Connector Contract    |
| - Requirement Agent           |                     | (Abstract Protocol / RFC-ADT) |
| - Discovery Agent             |                     | - search_cds()                |
| - Semantic Mapping Agent      |                     | - get_cds_metadata()          |
| - Decision Agent              |                     | - search_fields()             |
| - Data Model Agent            |                     | - get_dependencies()          |
| - CDS Generator Agent         |                     | - validate_cds()              |
| - Validation Agent            |                     | - activate_cds()              |
| - Governance Agent            |                     +---------------+---------------+
| - Audit & Impact Agent        |                                     |
+---------------+---------------+                                     | (Milestone 2+)
                |                                                     v
                v                                       +-------------------------------+
+-------------------------------+                       |       SAP S/4HANA 2023        |
|      PostgreSQL Database      |                       |    S4CORE 108 SP03 / ADT      |
|  (Audit Trails, Decisions)    |                       +-------------------------------+
+-------------------------------+
```

---

## 📁 Repository Structure

```
SAP-CDS-Agent/
├── docs/                        # Architecture, specs, and developer setup guides
│   ├── architecture.md
│   ├── dev-setup.md
│   └── sap-connector-spec.md
├── backend/                     # Python 3.12+ FastAPI backend
│   ├── src/
│   │   ├── api/                 # Endpoints, routers, correlation middleware
│   │   ├── core/                # Custom exceptions, security abstractions
│   │   ├── config.py            # Pydantic Settings configuration
│   │   ├── logging_config.py    # Structured logging with request tracing
│   │   ├── db/                  # SQLAlchemy async session management
│   │   ├── models/              # Pydantic domain models & ORM entities
│   │   ├── sap/                 # SAP Connector abstract interface & models
│   │   └── agents/              # Multi-agent LangGraph workflow skeletons
│   └── tests/                   # Pytest test suite
├── frontend/                    # Vite + React 18 + TypeScript + Tailwind CSS
│   ├── src/
│   │   ├── components/          # Shell, Navigation, Dashboard, MetricCards
│   │   ├── services/            # Backend API client
│   │   └── types/               # TypeScript models mirrored from backend
└── .env.example                 # Environment configuration template
```

---

## 🚀 Quick Start (Milestone 1)

See [`docs/dev-setup.md`](docs/dev-setup.md) for full setup instructions.

### 1. Backend Setup
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest tests -v
uvicorn src.main:app --reload --port 8000
```
Backend API will be accessible at: `http://127.0.0.1:8000` (Swagger docs: `http://127.0.0.1:8000/docs`).

### 2. Frontend Setup
```powershell
cd frontend
npm install
npm run dev
```
Frontend UI will be accessible at: `http://localhost:5173`.
