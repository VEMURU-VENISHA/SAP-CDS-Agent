# Development Setup Guide

This guide walks you through setting up and running the **SAP CDS Intelligence & Automation Platform** locally for development and testing.

---

## 1. Prerequisites

Verify installed software tools:
- **Python:** 3.12+
- **Node.js:** v20+ (v22 installed)
- **npm:** 10+
- **Git:** 2.40+

---

## 2. Backend Setup

1. Open PowerShell and navigate to the backend folder:
   ```powershell
   cd backend
   ```

2. Create and activate a Python virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```

3. Install production and development dependencies:
   ```powershell
   pip install -r requirements.txt -r requirements-dev.txt
   ```

4. Run the automated test suite:
   ```powershell
   pytest tests -v
   ```

5. Start the backend API server:
   ```powershell
   uvicorn src.main:app --reload --host 127.0.0.1 --port 8000
   ```

6. Open the interactive OpenAPI documentation in your browser:
   - Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
   - Health Check: [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health)

---

## 3. Frontend Setup

1. Open a new PowerShell terminal and navigate to the frontend folder:
   ```powershell
   cd frontend
   ```

2. Install npm dependencies:
   ```powershell
   npm install
   ```

3. Run the development server:
   ```powershell
   npm run dev
   ```

4. Access the web dashboard at: [http://localhost:5173](http://localhost:5173)

---

## 4. Environment Variables

The backend loads configuration from `.env` in the root directory or from system environment variables. Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
