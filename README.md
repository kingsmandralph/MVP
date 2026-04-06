# Federated National Digital Identity Gateway (FIG)

A centralized interoperability layer that allows government identity systems and private-sector platforms to verify citizens through one trusted, reusable digital identity flow.

**Core value:** Verify once, use everywhere. The gateway connects national ID, civil registry, tax, telecom, banking, and health systems so institutions can confirm identity securely, quickly, and consistently -- without creating a single giant database of personal data.

---

## Table of Contents

- [Problem](#problem)
- [Solution](#solution)
- [Architecture](#architecture)
- [Features](#features)
- [Getting Started](#getting-started)
- [How It Works](#how-it-works)
- [API Reference](#api-reference)
- [Supported Sectors](#supported-sectors)
- [Project Structure](#project-structure)
- [Default Credentials](#default-credentials)

---

## Problem

- Identity data is fragmented across ministries, agencies, banks, telecoms, hospitals, and service providers.
- Citizens repeat the same KYC and verification process every time they need a new service.
- Organizations spend heavily on onboarding, document checks, and fraud prevention.
- Weak interoperability delays service delivery, especially in rural and underserved communities.
- Fraud, duplicate records, and impersonation are easier to exploit without a unified system.

## Solution

The FIG Gateway is a secure interoperability system that connects identity providers and service providers through standard APIs, consent controls, and reusable digital credentials.

1. **Identity once** -- Citizens complete identity verification once (online or at enrollment centers).
2. **Reusable token** -- They receive a trusted JWT credential and QR code reusable across services.
3. **Verify anywhere** -- Connected institutions verify identity through the gateway without storing unnecessary sensitive data.

The gateway does not own citizen data. It acts as the trusted bridge that validates and routes identity claims between existing systems.

---

## Architecture

```
+---------------------+         +---------------------+
|  Government Systems |         |   Private Sector    |
|  - National ID DB   |         |   - Banks           |
|  - Civil Registry   |<------->|   - Telecoms        |
|  - Tax Authority    |   FIG   |   - Hospitals       |
|  - Immigration      |  Gateway|   - Schools         |
+---------------------+         +---------------------+
            |                            |
            v                            v
    +-----------------------------------------+
    |        FIG Gateway Core                 |
    |  - Enrollment & Verification Engine     |
    |  - Credential Issuance (JWT + QR)       |
    |  - Consent & Access Control             |
    |  - Audit & Compliance Logging           |
    |  - REST API for Institutions            |
    +-----------------------------------------+
            |                            |
            v                            v
    +----------------+         +------------------+
    | Citizen Portal |         | Institution Demo |
    | (Self-service) |         |  (Bank Portal)   |
    +----------------+         +------------------+
```

---

## Features

### Admin Gateway (port 5000)
- **Dashboard** -- Real-time stats: enrolled citizens, active credentials, verification requests, sector breakdown, recent activity feed.
- **Citizen Enrollment** -- Enroll citizens with identity data via online, enrollment center, or agent network channels.
- **Identity Verification** -- Verify enrolled citizens; auto-issues a JWT credential and QR code on verification.
- **Digital Credentials** -- Manage issued credentials (view, revoke). Each credential is a signed JWT token.
- **Verification Requests** -- View and process verification requests from institutions (approve/deny).
- **Consent Management** -- Track and revoke data-sharing consents between citizens and institutions.
- **Government Connectors** -- Register and manage connections to government identity source systems (national ID, civil registry, tax, immigration, voter rolls, social protection).
- **Institution Registry** -- Register private-sector institutions with unique API keys for gateway access.
- **Audit Logs** -- Immutable, paginated audit trail of all gateway operations with actor, target, IP, and timestamps.

### Citizen Portal (port 5000/portal)
- **View credential token and QR code** -- Copy token or scan QR to present to any institution.
- **Approve/deny verification requests** -- When an institution requests verification, the citizen controls consent.
- **Revoke consents** -- Remove an institution's access to your verified data at any time.

### Institution Demo Portal (port 5001)
- **Token-based authentication** -- Citizen pastes their FIG token; the bank validates it via the Gateway API for instant access.
- **Consent-based verification** -- Bank requests KYC/age/tax verification by National ID; citizen approves in the Citizen Portal.
- **Service access** -- Once authenticated, citizens can access banking services (accounts, loans, insurance, etc.) without paperwork.
- **Verification history** -- Track all verification requests and their status per session.

---

## Getting Started

### Prerequisites

- Python 3.9+
- pip

### Installation

```bash
git clone https://github.com/kingsmandralph/MVP.git
cd MVP

# Create virtual environment
python3 -m venv venv
source venv/bin/activate    # Linux/Mac
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Running

You need two terminals:

**Terminal 1 -- FIG Gateway (port 5000):**
```bash
python app.py
```

**Terminal 2 -- Demo Institution Portal (port 5001):**
```bash
python institution_demo.py
```

### Access Points

| Portal | URL | Purpose |
|--------|-----|---------|
| Admin Dashboard | http://localhost:5000 | Gateway administration |
| Citizen Portal | http://localhost:5000/portal | Citizen self-service |
| Demo Bank | http://localhost:5001 | Institution authentication demo |

---

## How It Works

### End-to-End Flow

```
1. ENROLL        Admin enrolls citizen with identity data
                 (National ID, name, DOB, biometrics, etc.)
                           |
                           v
2. VERIFY        Admin verifies the citizen's identity
                 Gateway auto-issues a JWT credential + QR code
                           |
                           v
3. GET TOKEN     Citizen logs into the Citizen Portal
                 Copies their credential token or scans QR
                           |
                           v
4. AUTHENTICATE  Citizen presents token at an institution
                 (paste into bank portal or scan QR)
                           |
                           v
5. VALIDATE      Institution calls FIG Gateway API:
                 POST /api/v1/credential/validate {token}
                 Gateway returns: {valid: true, national_id: "..."}
                           |
                           v
6. ACCESS        Citizen gets instant access to services
                 No paperwork, no repeated KYC
```

### Two Authentication Methods

**Method A -- Instant Token Verification:**
1. Citizen copies token from Citizen Portal.
2. Pastes into institution's portal.
3. Institution calls `POST /api/v1/credential/validate`.
4. Gateway confirms validity instantly.
5. Citizen is authenticated.

**Method B -- Consent-Based Verification (for deeper checks):**
1. Institution submits a verification request via `POST /api/v1/verify`.
2. Request appears in the citizen's portal as "Pending Consent".
3. Citizen approves or denies.
4. Institution polls `GET /api/v1/verify/{id}` for the result.
5. Gateway returns minimal data only (e.g., "identity valid", "age above 18").

---

## API Reference

All institution API endpoints require the `X-API-Key` header (except credential validation).

### Validate Credential Token

```
POST /api/v1/credential/validate
Content-Type: application/json

{
  "token": "<JWT credential token>"
}

Response (200):
{
  "valid": true,
  "national_id": "NID-2026-001",
  "issued_at": 1712275200,
  "expires_at": 1712361600
}
```

### Submit Verification Request

```
POST /api/v1/verify
X-API-Key: <institution_api_key>
Content-Type: application/json

{
  "national_id": "NID-2026-001",
  "verification_type": "identity",   // identity | age | tax_id | kyc | address | employment
  "consent_required": true
}

Response (202 if consent required, 200 if auto-approved):
{
  "request_id": 1,
  "status": "pending",
  "message": "Verification request submitted. Awaiting consent/approval."
}
```

### Check Verification Status

```
GET /api/v1/verify/<request_id>
X-API-Key: <institution_api_key>

Response (200):
{
  "request_id": 1,
  "status": "approved",
  "result": {
    "status": "verified",
    "identity_valid": true,
    "timestamp": "2026-04-05T01:13:18+00:00"
  }
}
```

### Verification Types

| Type | What it returns |
|------|----------------|
| `identity` | `identity_valid: true/false` |
| `age` | `age_above_18: true/false` |
| `tax_id` | `tax_id_matched: true/false` |
| `kyc` | `kyc_passed: true/false, name_verified: true/false` |
| `address` | Address confirmation |
| `employment` | Employment status |

---

## Supported Sectors

| Sector | Use Cases |
|--------|-----------|
| **Banking & Fintech** | Instant KYC, account opening, loan onboarding, digital wallet verification |
| **Telecommunications** | SIM registration, subscriber validation, mobile money onboarding |
| **Healthcare** | Patient matching, insurance validation, health record access |
| **Government** | Passport applications, tax filing, pension, business registration, e-voting |
| **Education** | Student registration, scholarship verification, certificate authentication |
| **Employment** | Payroll onboarding, background validation, labor-market inclusion |

---

## Project Structure

```
app.py                  # Main FIG Gateway application (Flask)
config.py               # Application configuration
models.py               # Database models (SQLAlchemy)
requirements.txt        # Python dependencies
institution_demo.py     # Demo institution portal (bank simulator)
static/
  css/
    style.css           # Gateway UI styles
templates/
  base.html             # Layout template
  login.html            # Admin login
  dashboard.html        # Admin dashboard
  enrollment.html       # Citizen enrollment list
  enrollment_form.html  # New citizen enrollment form
  citizen_detail.html   # Citizen detail view with QR
  credentials.html      # Credential management
  verifications.html    # Verification request management
  consent.html          # Consent management
  institutions.html     # Institution registry
  institution_form.html # New institution form
  connectors.html       # Government connector list
  connector_form.html   # New connector form
  audit.html            # Audit log viewer
  portal/
    login.html          # Citizen portal login
    dashboard.html      # Citizen self-service dashboard
```

---

## Default Credentials

| Portal | Username/ID | Password |
|--------|-------------|----------|
| Admin Dashboard | `admin` | `admin123` |
| Citizen Portal | Any verified citizen's National ID | N/A |

Demo data is seeded on first run: 4 government connectors (National ID, Civil Registry, Tax, Immigration) and 4 institutions (National Bank, TelcoNet, Central Hospital, Ministry of Education).

---

## Design Principles

- **Data minimization** -- The gateway returns only minimal proofs ("identity valid", "age above 18"), never full datasets.
- **Citizen consent** -- Citizens control what data is shared and can revoke access at any time.
- **Federation** -- The gateway bridges existing systems; it does not replace or centralize them.
- **Audit trail** -- Every operation is logged immutably for compliance and fraud monitoring.
- **Inclusion** -- Supports online, enrollment center, and agent network channels for citizens without internet access.
