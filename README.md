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
- **Self sign-up** -- Citizens create their FIG identity in one form and declare every ID they already hold (NIN, PVC, BVN, NHIS, TIN, driver license, etc.). The gateway federates each declared record from its source authority (NIMC, INEC, CBN, NHIS, FIRS, FRSC, PenCom, MoE).
- **Master credential token + QR** -- Auto-issued on signup. Reusable across every affiliated institution.
- **Identity completeness score** -- Dashboard shows what % of the 8 federated identity categories the citizen holds, with a per-category present/missing pill.
- **Nudges to complete missing IDs** -- For every missing category the citizen sees a prompt like "Take some time to complete your Health Insurance (NHIS) info — Upload to National Health Insurance Scheme", together with the institution sectors that will otherwise force them into manual KYC.
- **Consent audit trail** -- Every organization that has *ever* requested consent from the citizen is listed with timestamp, type, and resolution (approved / denied / pending).
- **Approve/deny verification requests** -- Citizen controls consent for every institutional request.
- **Revoke consents** -- Remove an institution's access at any time.

### Institution Demo Portal (port 5001)
- **3-Factor Authentication (the only sign-in path)** -- Token-only sign-in is disabled for security; every citizen must complete all three factors:
  1. **Master Token** (something we issue)
  2. **Portal Password** (something the citizen knows)
  3. **OTP delivered to the citizen's SIM** (something the citizen has)
  Each factor is verified through a dedicated FIG API and audited independently.
- **Category-aware KYC with manual fallback** -- When the bank runs `Banking KYC via FIG`, the gateway checks whether the citizen has a record in the *banking* category (BVN). If not, the gateway returns `manual_kyc_required` and the bank automatically routes the citizen into its own internal onboarding form. The citizen will see the matching nudge in their portal next time they sign in.
- **Consent-based verification** -- Bank requests KYC/age/tax verification by National ID; citizen approves in the Citizen Portal.
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
1. SIGN UP       Citizen self-signs up at /portal/signup, declaring
                 the IDs they already hold (NIN, PVC, BVN, NHIS, ...)
                 Gateway federates each one from its source authority
                 and issues a master credential token.
                           |
                           v
2. PRESENT       At a bank/telecom/hospital the citizen begins
                 3FA: pastes their master token + portal password,
                 then enters the OTP sent to their SIM.
                           |
                           v
3. VALIDATE      Institution calls the FIG 3FA API set:
                 - POST /api/v1/credential/validate
                 - POST /api/v1/auth/password
                 - POST /api/v1/auth/otp/request
                 - POST /api/v1/auth/otp/verify
                           |
                           v
4. CATEGORY      Institution asks FIG for the specific identity it
                 needs (e.g. banking -> BVN, healthcare -> NHIS):
                 POST /api/v1/verify/category
                           |
                +----------+----------+
                |                     |
        Record present         Record missing
                |                     |
                v                     v
        Instant verify        manual_kyc_required
                |                     |
                v                     v
        ACCESS GRANTED        FALL BACK to institution's
                              internal KYC form, and the
                              citizen is nudged in their
                              portal to register that ID.
```

### Authentication: 3-Factor Only

For security, **token-only sign-in is disabled**. Every institution must complete the full 3-factor flow before a citizen is considered authenticated. The `/api/v1/credential/validate` endpoint still exists, but it is consumed *internally* as factor 1 of the 3FA flow — no service can grant access on its result alone.

**3-Factor Authentication (the only supported sign-in path):**
1. Citizen submits master token + portal password to the institution.
2. Institution validates the token via `POST /api/v1/credential/validate` (factor 1 — something we issued).
3. Institution verifies the password via `POST /api/v1/auth/password` (factor 2 — something the citizen knows).
4. Institution requests an OTP via `POST /api/v1/auth/otp/request` — gateway delivers it to the citizen's registered SIM.
5. Citizen enters the OTP; institution verifies it via `POST /api/v1/auth/otp/verify` (factor 3 — something the citizen has).
6. Each factor is logged independently in the immutable audit trail.

**Consent-Based Verification (separate flow, used *after* sign-in for deep checks):**
1. Institution submits a verification request via `POST /api/v1/verify`.
2. Request appears in the citizen's portal as "Pending Consent".
3. Citizen approves or denies.
4. Institution polls `GET /api/v1/verify/{id}` for the result.
5. Gateway returns minimal data only.

### Category Verification with Manual KYC Fallback

When an institution needs a specific identity (a hospital needs the citizen's NHIS, a bank needs BVN, etc.), it calls:

```
POST /api/v1/verify/category
{ "national_id": "NID-2026-002", "category": "health" }
```

If the citizen has the record, the gateway returns it instantly. If not, it returns `manual_kyc_required: true` together with a `nudge` describing what the citizen should register and where. The institution then routes the citizen into its own internal onboarding flow, and the missing-ID nudge appears on the citizen's dashboard so they can complete it ahead of time next time.

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

### 3-Factor Authentication APIs

All require the `X-API-Key` header.

```
POST /api/v1/auth/password
{ "token": "<master JWT>", "password": "demo1234" }
-> { "factor": "password", "verified": true, "national_id": "NID-2026-001" }

POST /api/v1/auth/otp/request
{ "token": "<master JWT>" }
-> { "sent": true, "channel": "sim", "masked_phone": "0803****67",
     "expires_in_minutes": 5, "demo_code": "534939" }
   (demo_code is returned only in the demo build; in production
    the OTP is delivered exclusively via SMS to the SIM)

POST /api/v1/auth/otp/verify
{ "token": "<master JWT>", "code": "534939" }
-> { "factor": "otp", "verified": true, "3fa_complete": true,
     "national_id": "NID-2026-001" }
```

### Category Verification (with manual KYC fallback)

```
POST /api/v1/verify/category
X-API-Key: <institution_api_key>
{ "national_id": "NID-2026-002", "category": "health" }

If the citizen has the record:
{
  "status": "verified",
  "manual_kyc_required": false,
  "category": "health",
  "source": "NHIS",
  "record_id": "NHIS-AOK-9091",
  "verified_at": "..."
}

If the citizen does NOT have the record:
{
  "status": "manual_kyc_required",
  "manual_kyc_required": true,
  "category": "health",
  "reason": "Citizen has no Health Insurance (NHIS) record on file",
  "nudge": "Citizen should register Health Insurance (NHIS) with National Health Insurance Scheme"
}
```

Categories: `foundational` (NIN), `voter` (PVC), `tax` (TIN), `health` (NHIS), `education`, `employment` (PenCom), `banking` (BVN), `driving` (FRSC).

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
    login.html          # Citizen portal login (national ID + password)
    signup.html         # Citizen self-signup with declared identities
    dashboard.html      # Self-service dashboard with completeness, nudges, audit
```

---

## Default Credentials

| Portal | Username/ID | Password |
|--------|-------------|----------|
| Admin Dashboard | `admin` | `admin123` |
| Citizen Portal — Ada (complete identity) | `NID-2026-009` | `demo1234` |
| Citizen Portal — Bola (missing health record) | `NID-2026-002` | `demo1234` |

Demo data is seeded on first run:
- 4 government connectors (National ID, Civil Registry, Tax, Immigration)
- 4 institutions (National Bank, TelcoNet, Central Hospital, Ministry of Education)
- 2 demo citizens with passwords, master tokens, and federated identity records
  - **Ada Okafor** holds every category — every institution verifies her instantly
  - **Bola Adeyemi** is missing his NHIS record — hospitals will route him to manual KYC, and his dashboard shows the nudge to register with NHIS

---

## Design Principles

- **Data minimization** -- The gateway returns only minimal proofs ("identity valid", "age above 18"), never full datasets.
- **Citizen consent** -- Citizens control what data is shared and can revoke access at any time.
- **Federation** -- The gateway bridges existing systems; it does not replace or centralize them.
- **Audit trail** -- Every operation is logged immutably for compliance and fraud monitoring.
- **Inclusion** -- Supports online, enrollment center, and agent network channels for citizens without internet access.
