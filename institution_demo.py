"""
Demo Institution Portal (e.g. National Bank)
=============================================
This simulates how a real institution (bank, telecom, hospital, etc.)
integrates with the FIG Gateway to authenticate citizens using their
digital credentials.

Flow:
1. Citizen visits the institution's portal
2. Citizen presents their FIG credential token (paste or QR scan)
3. Institution's backend calls FIG Gateway API to validate the token
4. If valid, citizen is authenticated and can access services
5. Institution can also request deeper verification (KYC, age, tax ID)
   which requires citizen consent through the FIG Citizen Portal

Run: python institution_demo.py
(Runs on port 5001 while the FIG Gateway runs on port 5000)
"""

import json
from datetime import datetime

import requests
from flask import Flask, render_template_string, request, redirect, session, flash, url_for

app = Flask(__name__)
app.secret_key = 'demo-institution-secret-key'

# ─── Configuration ─────────────────────────────────────────
# In production, these come from the institution's config after
# registering with the FIG Gateway
FIG_GATEWAY_URL = 'http://localhost:5000'
INSTITUTION_API_KEY = None  # Set at startup from the gateway DB

INSTITUTION_NAME = 'National Bank of Nigeria'
INSTITUTION_SECTOR = 'Banking & Financial Services'
# Identity category this institution requires for KYC. A hospital would set 'health'.
INSTITUTION_REQUIRED_CATEGORY = 'banking'


# ─── HTML Templates ────────────────────────────────────────

BASE_CSS = """
<style>
    :root { --primary: #1a365d; --accent: #c05621; --success: #276749; --bg: #f7fafc; }
    * { margin:0; padding:0; box-sizing:border-box; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:var(--bg); color:#1a202c; }
    .topbar { background:var(--primary); color:white; padding:1rem 2rem; display:flex; justify-content:space-between; align-items:center; }
    .topbar h1 { font-size:1.1rem; }
    .topbar .sector { font-size:0.75rem; opacity:0.7; }
    .topbar a { color:rgba(255,255,255,0.8); text-decoration:none; font-size:0.85rem; }
    .container { max-width:900px; margin:2rem auto; padding:0 1.5rem; }
    .card { background:white; border:1px solid #e2e8f0; border-radius:8px; padding:1.5rem; margin-bottom:1.5rem; }
    .card h3 { font-size:1rem; color:var(--primary); margin-bottom:1rem; padding-bottom:0.5rem; border-bottom:1px solid #e2e8f0; }
    .btn { display:inline-flex; align-items:center; padding:0.6rem 1.2rem; border:none; border-radius:6px; font-size:0.85rem; font-weight:500; cursor:pointer; text-decoration:none; }
    .btn-primary { background:var(--accent); color:white; }
    .btn-primary:hover { background:#9c4221; }
    .btn-outline { background:transparent; border:1px solid #e2e8f0; color:#1a202c; }
    .form-group { margin-bottom:1rem; }
    .form-group label { display:block; font-size:0.8rem; font-weight:600; color:#718096; margin-bottom:0.35rem; text-transform:uppercase; }
    .form-group input, .form-group textarea, .form-group select { width:100%; padding:0.6rem 0.8rem; border:1px solid #e2e8f0; border-radius:6px; font-size:0.9rem; font-family:inherit; }
    .form-group textarea { font-family: monospace; font-size:0.8rem; }
    .alert { padding:0.75rem 1rem; border-radius:6px; margin-bottom:1rem; font-size:0.875rem; }
    .alert-success { background:#c6f6d5; color:#276749; }
    .alert-error { background:#fed7d7; color:#9b2c2c; }
    .alert-warning { background:#fefcbf; color:#975a16; }
    .badge { display:inline-block; padding:0.2rem 0.6rem; border-radius:12px; font-size:0.7rem; font-weight:600; text-transform:uppercase; }
    .badge-success { background:#c6f6d5; color:#276749; }
    .badge-danger { background:#fed7d7; color:#9b2c2c; }
    .badge-info { background:#bee3f8; color:#2a4365; }
    .result-box { background:#1a202c; color:#68d391; font-family:monospace; font-size:0.8rem; padding:1rem; border-radius:6px; white-space:pre-wrap; margin-top:1rem; }
    .service-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px,1fr)); gap:1rem; margin-top:1rem; }
    .service-card { background:#f0fff4; border:1px solid #c6f6d5; border-radius:8px; padding:1rem; text-align:center; }
    .service-card h4 { font-size:0.9rem; color:#276749; margin-bottom:0.25rem; }
    .service-card p { font-size:0.75rem; color:#718096; }
    .flow-steps { display:flex; gap:0.5rem; margin:1rem 0; flex-wrap:wrap; }
    .flow-step { flex:1; min-width:150px; background:#ebf8ff; border:1px solid #bee3f8; border-radius:8px; padding:0.75rem; text-align:center; }
    .flow-step .num { display:inline-block; background:#2b6cb0; color:white; width:24px; height:24px; line-height:24px; border-radius:50%; font-size:0.75rem; font-weight:700; margin-bottom:0.35rem; }
    .flow-step p { font-size:0.78rem; color:#4a5568; }
    .authed-banner { background:linear-gradient(135deg,#276749,#2f855a); color:white; border-radius:8px; padding:1.5rem; margin-bottom:1.5rem; }
    .authed-banner h2 { font-size:1.2rem; margin-bottom:0.25rem; }
    .authed-banner p { font-size:0.85rem; opacity:0.9; }
    table { width:100%; border-collapse:collapse; font-size:0.85rem; }
    th,td { padding:0.6rem 0.75rem; text-align:left; border-bottom:1px solid #e2e8f0; }
    th { background:#f7fafc; font-size:0.75rem; text-transform:uppercase; color:#718096; }
</style>
"""

LOGIN_PAGE = BASE_CSS + """
<div class="topbar">
    <div>
        <h1>{{ name }}</h1>
        <div class="sector">{{ sector }} | Powered by FIG Gateway</div>
    </div>
</div>
<div class="container">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <div class="card">
        <h3>Authenticate with Your Digital Identity</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:1rem;">
            Welcome to {{ name }}. Instead of filling out KYC paperwork, simply present your
            FIG Digital Credential to verify your identity instantly.
        </p>

        <div class="flow-steps">
            <div class="flow-step">
                <div class="num">1</div>
                <p><strong>Get your token</strong> from the FIG Citizen Portal</p>
            </div>
            <div class="flow-step">
                <div class="num">2</div>
                <p><strong>Paste it below</strong> or scan your QR code</p>
            </div>
            <div class="flow-step">
                <div class="num">3</div>
                <p><strong>Instant verification</strong> via the FIG Gateway</p>
            </div>
            <div class="flow-step">
                <div class="num">4</div>
                <p><strong>Access services</strong> immediately</p>
            </div>
        </div>

        <form method="POST" action="/authenticate">
            <div class="form-group">
                <label>FIG Credential Token</label>
                <textarea name="token" rows="4" required placeholder="Paste your FIG credential token here..."></textarea>
            </div>
            <button type="submit" class="btn btn-primary">Verify & Sign In</button>
        </form>
    </div>

    <div class="card" style="border:2px solid #c05621;">
        <h3>3-Factor Sign-In (Recommended for High-Value Onboarding)</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:1rem;">
            Highest assurance: <strong>Master Token</strong> (FIG-issued) + <strong>Password</strong> (you know) + <strong>OTP from your SIM</strong> (you have).
        </p>
        <form method="POST" action="/3fa/start">
            <div class="form-group">
                <label>Master Token</label>
                <textarea name="token" rows="3" required placeholder="Paste your FIG master token"></textarea>
            </div>
            <div class="form-group">
                <label>Portal Password</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit" class="btn btn-primary">Begin 3FA</button>
        </form>
    </div>

    <div class="card">
        <h3>Or: Verify by National ID (Requires Your Consent)</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:1rem;">
            If you don't have your token handy, we can request verification through the gateway.
            You'll need to approve this in the FIG Citizen Portal.
        </p>
        <form method="POST" action="/request-verification">
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                <div class="form-group">
                    <label>National ID</label>
                    <input type="text" name="national_id" required placeholder="e.g. NID-2026-001">
                </div>
                <div class="form-group">
                    <label>Verification Type</label>
                    <select name="verification_type">
                        <option value="identity">Identity Verification</option>
                        <option value="kyc">Full KYC</option>
                        <option value="age">Age Verification</option>
                        <option value="tax_id">Tax ID Match</option>
                    </select>
                </div>
            </div>
            <button type="submit" class="btn btn-outline">Request Verification</button>
        </form>
    </div>
</div>
"""

AUTHENTICATED_PAGE = BASE_CSS + """
<div class="topbar">
    <div>
        <h1>{{ name }}</h1>
        <div class="sector">{{ sector }}</div>
    </div>
    <a href="/logout">Sign Out</a>
</div>
<div class="container">
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}

    <div class="authed-banner">
        <h2>Welcome, Verified Customer</h2>
        <p>National ID: {{ identity.national_id }} | Authenticated via FIG Gateway at {{ identity.verified_at }}</p>
    </div>

    <div class="card">
        <h3>Identity Verification Details</h3>
        <table>
            <tr><th style="width:200px">Field</th><th>Value</th></tr>
            <tr><td>National ID</td><td>{{ identity.national_id }}</td></tr>
            <tr><td>Verification Status</td><td><span class="badge badge-success">Verified</span></td></tr>
            <tr><td>Verified At</td><td>{{ identity.verified_at }}</td></tr>
            <tr><td>Credential Valid</td><td><span class="badge badge-success">Yes</span></td></tr>
            <tr><td>Gateway Response</td><td>Identity confirmed via FIG federated verification</td></tr>
        </table>
    </div>

    <div class="card" style="border:2px solid #c05621;">
        <h3>Sector KYC Check ({{ ' ' }} category: banking)</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:0.75rem;">
            We need to confirm your <strong>banking identity (BVN)</strong> via FIG. If FIG doesn't have it, you'll be routed to our internal manual KYC.
        </p>
        <form method="POST" action="/category-verify">
            <button type="submit" class="btn btn-primary">Run Banking KYC via FIG</button>
        </form>
    </div>

    <div class="card">
        <h3>Available Services</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:0.5rem;">
            Because your identity is verified through FIG, you can access all services without additional paperwork.
        </p>
        <div class="service-grid">
            <div class="service-card">
                <h4>Open Account</h4>
                <p>Savings, current, or fixed deposit -- instant onboarding</p>
            </div>
            <div class="service-card">
                <h4>Apply for Loan</h4>
                <p>Personal, business, or mortgage loan application</p>
            </div>
            <div class="service-card">
                <h4>Digital Wallet</h4>
                <p>Mobile money and digital payment services</p>
            </div>
            <div class="service-card">
                <h4>Insurance</h4>
                <p>Health, auto, and life insurance enrollment</p>
            </div>
            <div class="service-card">
                <h4>Investment</h4>
                <p>Stocks, bonds, and mutual fund accounts</p>
            </div>
            <div class="service-card">
                <h4>Card Services</h4>
                <p>Debit and credit card issuance</p>
            </div>
        </div>
    </div>

    <div class="card">
        <h3>Request Additional Verification</h3>
        <p style="font-size:0.85rem; color:#718096; margin-bottom:1rem;">
            Need more data points? Request specific verifications. The citizen controls consent.
        </p>
        <form method="POST" action="/additional-verification">
            <div style="display:flex; gap:1rem; align-items:end;">
                <div class="form-group" style="flex:1; margin-bottom:0;">
                    <label>Verification Type</label>
                    <select name="verification_type">
                        <option value="kyc">Full KYC</option>
                        <option value="age">Age Check (18+)</option>
                        <option value="tax_id">Tax ID Match</option>
                        <option value="address">Address Verification</option>
                    </select>
                </div>
                <button type="submit" class="btn btn-primary" style="margin-bottom:0;">Request</button>
            </div>
        </form>
    </div>

    {% if verification_history %}
    <div class="card">
        <h3>Verification History</h3>
        <table>
            <thead><tr><th>Request ID</th><th>Type</th><th>Status</th><th>Result</th></tr></thead>
            <tbody>
                {% for v in verification_history %}
                <tr>
                    <td>#{{ v.id }}</td>
                    <td><span class="badge badge-info">{{ v.type }}</span></td>
                    <td>
                        {% if v.status == 'approved' %}<span class="badge badge-success">Approved</span>
                        {% elif v.status == 'pending' %}<span class="badge" style="background:#fefcbf;color:#975a16">Pending Consent</span>
                        {% else %}<span class="badge badge-danger">{{ v.status }}</span>{% endif %}
                    </td>
                    <td style="font-size:0.8rem">{{ v.result or 'Awaiting citizen consent' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}
</div>
"""

OTP_PAGE = BASE_CSS + """
<div class="topbar"><div><h1>{{ name }}</h1><div class="sector">{{ sector }}</div></div></div>
<div class="container">
    {% for cat, msg in messages %}<div class="alert alert-{{ cat }}">{{ msg }}</div>{% endfor %}
    <div class="card">
        <h3>Step 3 of 3 — Enter OTP from your SIM</h3>
        <p style="font-size:0.85rem; color:#718096;">
            Master token verified. Password verified. An OTP has been sent to <strong>{{ masked_phone }}</strong>.
        </p>
        {% if demo_code %}
        <div class="alert alert-warning"><strong>Demo:</strong> code is <code>{{ demo_code }}</code> (in production this would only be on the SIM).</div>
        {% endif %}
        <form method="POST" action="/3fa/verify-otp">
            <div class="form-group"><label>OTP Code</label><input type="text" name="code" required maxlength="6" autofocus></div>
            <button type="submit" class="btn btn-primary">Complete Sign-In</button>
        </form>
    </div>
</div>
"""

MANUAL_KYC_PAGE = BASE_CSS + """
<div class="topbar"><div><h1>{{ name }}</h1><div class="sector">{{ sector }}</div></div><a href="/dashboard">Back</a></div>
<div class="container">
    <div class="card" style="border:2px solid #c05621;">
        <h3>Manual KYC Required</h3>
        <div class="alert alert-warning">
            FIG could not verify your <strong>{{ category }}</strong> identity:
            {{ reason }}
        </div>
        <p style="font-size:0.85rem; color:#4a5568;">
            <strong>{{ nudge }}</strong>
        </p>
        <p style="font-size:0.85rem; color:#718096; margin-top:1rem;">
            Because we don't have this on file, you must complete <strong>{{ name }}'s</strong> internal onboarding form below.
        </p>
        <form style="margin-top:1rem;">
            <div class="form-group"><label>Full Legal Name</label><input type="text" placeholder="As on ID"></div>
            <div class="form-group"><label>Document Upload (passport/ID)</label><input type="file"></div>
            <div class="form-group"><label>Proof of Address</label><input type="file"></div>
            <button type="button" class="btn btn-primary">Submit Manual KYC</button>
        </form>
    </div>
</div>
"""

VERIFICATION_REQUESTED_PAGE = BASE_CSS + """
<div class="topbar">
    <div>
        <h1>{{ name }}</h1>
        <div class="sector">{{ sector }}</div>
    </div>
</div>
<div class="container">
    <div class="card">
        <h3>Verification Requested</h3>
        <div style="background:#ebf8ff; border:1px solid #bee3f8; border-radius:8px; padding:1.25rem; margin-bottom:1rem;">
            <p style="font-size:0.9rem; color:#2a4365; margin-bottom:0.5rem;">
                <strong>Request ID: #{{ request_id }}</strong>
            </p>
            <p style="font-size:0.85rem; color:#4a5568;">
                A verification request has been sent to the FIG Gateway for National ID <strong>{{ national_id }}</strong>.
            </p>
        </div>

        <div class="flow-steps">
            <div class="flow-step" style="background:#c6f6d5; border-color:#9ae6b4;">
                <div class="num" style="background:#276749;">1</div>
                <p><strong>Request sent</strong></p>
            </div>
            <div class="flow-step">
                <div class="num">2</div>
                <p><strong>Citizen approves</strong> consent in FIG Portal</p>
            </div>
            <div class="flow-step">
                <div class="num">3</div>
                <p><strong>Gateway responds</strong> with verification</p>
            </div>
            <div class="flow-step">
                <div class="num">4</div>
                <p><strong>Access granted</strong></p>
            </div>
        </div>

        <p style="font-size:0.85rem; color:#718096; margin-bottom:1rem;">
            The citizen needs to approve this request in their <strong>FIG Citizen Portal</strong>
            (<a href="http://localhost:5000/portal" style="color:#2b6cb0">http://localhost:5000/portal</a>).
            Once approved, click below to check the status.
        </p>

        <div style="display:flex; gap:0.75rem;">
            <form method="POST" action="/check-verification">
                <input type="hidden" name="request_id" value="{{ request_id }}">
                <button type="submit" class="btn btn-primary">Check Verification Status</button>
            </form>
            <a href="/" class="btn btn-outline">Back to Login</a>
        </div>

        {% if result %}
        <div style="margin-top:1rem;">
            {% if result.status == 'approved' %}
            <div class="alert alert-success">
                Verification approved! <a href="/" style="color:#276749; font-weight:600">Proceed to sign in with token</a>
            </div>
            {% elif result.status == 'pending' %}
            <div class="alert alert-warning">Still pending. The citizen has not yet approved the request.</div>
            {% else %}
            <div class="alert alert-error">Verification {{ result.status }}. {{ result.get('result', {}).get('reason', '') }}</div>
            {% endif %}
            <div class="result-box">{{ result | tojson(indent=2) }}</div>
        </div>
        {% endif %}
    </div>
</div>
"""


# ─── Routes ────────────────────────────────────────────────

@app.route('/')
def index():
    if 'identity' in session:
        return redirect(url_for('dashboard'))
    messages = session.pop('_messages', [])
    return render_template_string(LOGIN_PAGE, name=INSTITUTION_NAME,
                                 sector=INSTITUTION_SECTOR, messages=messages)


@app.route('/authenticate', methods=['POST'])
def authenticate():
    """Citizen presents their FIG credential token for instant authentication."""
    token = request.form.get('token', '').strip()
    if not token:
        _flash('Please provide your credential token.', 'error')
        return redirect('/')

    # Call FIG Gateway API to validate the token
    try:
        resp = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/credential/validate',
            json={'token': token},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway. Is it running on port 5000? Error: {e}', 'error')
        return redirect('/')

    if data.get('valid'):
        session['identity'] = {
            'national_id': data['national_id'],
            'verified_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'token': token
        }
        session['verification_history'] = []
        _flash('Identity verified successfully via FIG Gateway. Welcome!', 'success')
        return redirect(url_for('dashboard'))
    else:
        _flash(f'Credential validation failed: {data.get("reason", "Unknown error")}', 'error')
        return redirect('/')


@app.route('/request-verification', methods=['POST'])
def request_verification():
    """Institution requests verification via National ID (requires citizen consent)."""
    national_id = request.form.get('national_id', '').strip()
    verification_type = request.form.get('verification_type', 'identity')

    if not INSTITUTION_API_KEY:
        _flash('Institution API key not configured. Run the FIG Gateway first.', 'error')
        return redirect('/')

    try:
        resp = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/verify',
            json={
                'national_id': national_id,
                'verification_type': verification_type,
                'consent_required': True
            },
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect('/')

    if 'request_id' in data:
        return render_template_string(VERIFICATION_REQUESTED_PAGE,
                                      name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                      request_id=data['request_id'],
                                      national_id=national_id, result=None)
    else:
        _flash(f'Error: {data.get("error", "Unknown")}', 'error')
        return redirect('/')


@app.route('/check-verification', methods=['POST'])
def check_verification():
    """Check the status of a pending verification request."""
    request_id = request.form.get('request_id')

    try:
        resp = requests.get(
            f'{FIG_GATEWAY_URL}/api/v1/verify/{request_id}',
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect('/')

    return render_template_string(VERIFICATION_REQUESTED_PAGE,
                                  name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                  request_id=request_id, national_id='(from request)',
                                  result=data)


@app.route('/dashboard')
def dashboard():
    if 'identity' not in session:
        return redirect('/')
    messages = session.pop('_messages', [])
    return render_template_string(AUTHENTICATED_PAGE,
                                  name=INSTITUTION_NAME, sector=INSTITUTION_SECTOR,
                                  identity=session['identity'],
                                  verification_history=session.get('verification_history', []),
                                  messages=messages)


@app.route('/additional-verification', methods=['POST'])
def additional_verification():
    """Request additional verification for an already-authenticated citizen."""
    if 'identity' not in session:
        return redirect('/')

    verification_type = request.form.get('verification_type', 'kyc')
    national_id = session['identity']['national_id']

    try:
        resp = requests.post(
            f'{FIG_GATEWAY_URL}/api/v1/verify',
            json={
                'national_id': national_id,
                'verification_type': verification_type,
                'consent_required': True
            },
            headers={'X-API-Key': INSTITUTION_API_KEY},
            timeout=10
        )
        data = resp.json()
    except requests.RequestException as e:
        _flash(f'Cannot reach FIG Gateway: {e}', 'error')
        return redirect(url_for('dashboard'))

    history = session.get('verification_history', [])
    if 'request_id' in data:
        entry = {
            'id': data['request_id'],
            'type': verification_type,
            'status': data.get('status', 'pending'),
            'result': json.dumps(data.get('result')) if data.get('result') else None
        }
        history.append(entry)
        session['verification_history'] = history
        _flash(f'Verification request #{data["request_id"]} submitted. Citizen must approve in FIG Portal.', 'success')
    else:
        _flash(f'Error: {data.get("error", "Unknown")}', 'error')

    return redirect(url_for('dashboard'))


@app.route('/3fa/start', methods=['POST'])
def three_fa_start():
    """Step 1+2: validate master token, then verify password via FIG API."""
    token = request.form.get('token', '').strip()
    password = request.form.get('password', '').strip()

    # Step 1: token validity
    try:
        r1 = requests.post(f'{FIG_GATEWAY_URL}/api/v1/credential/validate',
                           json={'token': token}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect('/')
    if not r1.get('valid'):
        _flash(f'Master token invalid: {r1.get("reason", "unknown")}', 'error')
        return redirect('/')

    # Step 2: password
    try:
        r2 = requests.post(f'{FIG_GATEWAY_URL}/api/v1/auth/password',
                           json={'token': token, 'password': password},
                           headers={'X-API-Key': INSTITUTION_API_KEY}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect('/')
    if not r2.get('verified'):
        _flash(f'Password failed: {r2.get("reason", "denied")}', 'error')
        return redirect('/')

    # Step 3a: request OTP
    try:
        r3 = requests.post(f'{FIG_GATEWAY_URL}/api/v1/auth/otp/request',
                           json={'token': token},
                           headers={'X-API-Key': INSTITUTION_API_KEY}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect('/')

    session['3fa_token'] = token
    session['3fa_national_id'] = r2['national_id']
    return render_template_string(OTP_PAGE, name=INSTITUTION_NAME,
                                  sector=INSTITUTION_SECTOR,
                                  masked_phone=r3.get('masked_phone', 'SIM'),
                                  demo_code=r3.get('demo_code'),
                                  messages=session.pop('_messages', []))


@app.route('/3fa/verify-otp', methods=['POST'])
def three_fa_verify_otp():
    code = request.form.get('code', '').strip()
    token = session.get('3fa_token')
    if not token:
        _flash('3FA session expired. Start again.', 'error')
        return redirect('/')
    try:
        r = requests.post(f'{FIG_GATEWAY_URL}/api/v1/auth/otp/verify',
                          json={'token': token, 'code': code},
                          headers={'X-API-Key': INSTITUTION_API_KEY}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect('/')
    if not r.get('verified'):
        _flash(f'OTP failed: {r.get("reason", "denied")}', 'error')
        return redirect('/')

    session['identity'] = {
        'national_id': r['national_id'],
        'verified_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        'token': token,
        'auth_method': '3FA (token + password + SIM OTP)',
    }
    session['verification_history'] = []
    _flash('3FA complete. Welcome — fully verified.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/category-verify', methods=['POST'])
def category_verify():
    """Try a category-scoped verify; fall back to manual KYC if missing."""
    if 'identity' not in session:
        return redirect('/')
    try:
        r = requests.post(f'{FIG_GATEWAY_URL}/api/v1/verify/category',
                          json={'national_id': session['identity']['national_id'],
                                'category': INSTITUTION_REQUIRED_CATEGORY},
                          headers={'X-API-Key': INSTITUTION_API_KEY}, timeout=10).json()
    except requests.RequestException as e:
        _flash(f'Gateway unreachable: {e}', 'error')
        return redirect(url_for('dashboard'))

    if r.get('manual_kyc_required'):
        return render_template_string(MANUAL_KYC_PAGE, name=INSTITUTION_NAME,
                                      sector=INSTITUTION_SECTOR,
                                      category=r.get('category', INSTITUTION_REQUIRED_CATEGORY),
                                      reason=r.get('reason', ''),
                                      nudge=r.get('nudge', ''))
    _flash(f"{INSTITUTION_REQUIRED_CATEGORY} verified via FIG (record id: {r.get('record_id')})", 'success')
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


def _flash(msg, cat):
    msgs = session.get('_messages', [])
    msgs.append((cat, msg))
    session['_messages'] = msgs


def get_institution_api_key():
    """Fetch the first institution's API key from the FIG Gateway for demo purposes."""
    global INSTITUTION_API_KEY
    try:
        # We need to query the gateway DB directly since we're a demo
        import sys
        sys.path.insert(0, '.')
        from app import app as gateway_app
        from models import Institution
        with gateway_app.app_context():
            inst = Institution.query.filter_by(name='National Bank').first()
            if inst:
                INSTITUTION_API_KEY = inst.api_key
                print(f'[*] Using API key from institution: {inst.name}')
                print(f'[*] API Key: {INSTITUTION_API_KEY[:20]}...')
            else:
                print('[!] No institution found. Register one in the FIG Gateway first.')
    except Exception as e:
        print(f'[!] Could not load API key from gateway DB: {e}')
        print('[!] Make sure the FIG Gateway has been started at least once to initialize the DB.')


if __name__ == '__main__':
    print('=' * 60)
    print('  Demo Institution Portal: National Bank of Nigeria')
    print('  Authenticates citizens via FIG Gateway credentials')
    print('=' * 60)
    print()
    print('[*] FIG Gateway must be running on http://localhost:5000')
    print('[*] This demo runs on http://localhost:5001')
    print()

    get_institution_api_key()

    print()
    print('[*] Starting institution portal...')
    print('[*] Open http://localhost:5001 in your browser')
    print()
    app.run(debug=True, host='0.0.0.0', port=5001)
