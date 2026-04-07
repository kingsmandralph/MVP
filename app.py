import json
import secrets
import io
import base64
from datetime import datetime, timedelta, timezone, date

import jwt
import qrcode
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)

from config import Config
from models import (
    db, AdminUser, Citizen, Institution, Credential,
    VerificationRequest, ConsentRecord, AuditLog, GovernmentConnector,
    IdentityRecord, OTPCode
)

app = Flask(__name__)
app.config.from_object(Config)
# Make all sessions (admin + citizen) persist across reloads. Without this,
# Flask falls back to a browser-session cookie which some browsers drop on
# refresh, silently logging the citizen out.
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db.init_app(app)


@app.before_request
def _make_session_permanent():
    session.permanent = True
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(AdminUser, int(user_id))


def log_audit(event_type, actor_type=None, actor_id=None,
              target_type=None, target_id=None, details=None):
    entry = AuditLog(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id else None,
        target_type=target_type,
        target_id=str(target_id) if target_id else None,
        details=details,
        ip_address=request.remote_addr if request else None
    )
    db.session.add(entry)
    db.session.commit()


def generate_credential_token(citizen):
    payload = {
        'sub': citizen.national_id,
        'name': f'{citizen.first_name} {citizen.last_name}',
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=app.config['JWT_EXPIRY_HOURS']),
        'type': 'identity_credential',
        'gateway': 'FIG'
    }
    return jwt.encode(payload, app.config['JWT_SECRET'], algorithm='HS256')


def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


# ─── Authentication ────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = AdminUser.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            log_audit('admin_login', 'admin', user.id)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    log_audit('admin_logout', 'admin', current_user.id)
    logout_user()
    return redirect(url_for('login'))


# ─── Dashboard ─────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    stats = {
        'total_citizens': Citizen.query.count(),
        'verified_citizens': Citizen.query.filter_by(enrollment_status='verified').count(),
        'pending_citizens': Citizen.query.filter_by(enrollment_status='pending').count(),
        'total_institutions': Institution.query.filter_by(status='active').count(),
        'total_credentials': Credential.query.filter_by(status='active').count(),
        'total_verifications': VerificationRequest.query.count(),
        'pending_verifications': VerificationRequest.query.filter_by(status='pending').count(),
        'approved_verifications': VerificationRequest.query.filter_by(status='approved').count(),
        'total_consents': ConsentRecord.query.filter_by(granted=True).count(),
        'connectors_active': GovernmentConnector.query.filter_by(status='active').count(),
    }
    recent_activity = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    recent_verifications = VerificationRequest.query.order_by(
        VerificationRequest.created_at.desc()
    ).limit(5).all()

    # Sector breakdown
    sector_counts = {}
    for sector in Config.SUPPORTED_SECTORS:
        sector_counts[sector] = Institution.query.filter_by(sector=sector, status='active').count()

    return render_template('dashboard.html', stats=stats,
                           recent_activity=recent_activity,
                           recent_verifications=recent_verifications,
                           sector_counts=sector_counts)


# ─── Citizen Enrollment ───────────────────────────────────

@app.route('/enrollment')
@login_required
def enrollment_list():
    citizens = Citizen.query.order_by(Citizen.enrolled_at.desc()).all()
    return render_template('enrollment.html', citizens=citizens)


@app.route('/enrollment/new', methods=['GET', 'POST'])
@login_required
def enrollment_new():
    if request.method == 'POST':
        national_id = request.form['national_id'].strip()
        if Citizen.query.filter_by(national_id=national_id).first():
            flash('A citizen with this National ID already exists.', 'error')
            return render_template('enrollment_form.html')

        citizen = Citizen(
            national_id=national_id,
            first_name=request.form['first_name'].strip(),
            last_name=request.form['last_name'].strip(),
            date_of_birth=datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date(),
            gender=request.form.get('gender', ''),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            address=request.form.get('address', '').strip(),
            enrollment_channel=request.form.get('enrollment_channel', 'online'),
            biometric_hash=secrets.token_hex(32)
        )
        db.session.add(citizen)
        db.session.commit()
        log_audit('citizen_enrolled', 'admin', current_user.id,
                  'citizen', citizen.id, f'National ID: {national_id}')
        flash(f'Citizen {citizen.first_name} {citizen.last_name} enrolled successfully.', 'success')
        return redirect(url_for('enrollment_list'))
    return render_template('enrollment_form.html')


@app.route('/enrollment/<int:citizen_id>/verify', methods=['POST'])
@login_required
def verify_citizen(citizen_id):
    citizen = db.session.get(Citizen, citizen_id)
    if not citizen:
        flash('Citizen not found.', 'error')
        return redirect(url_for('enrollment_list'))

    citizen.enrollment_status = 'verified'
    citizen.verified_at = datetime.now(timezone.utc)
    db.session.commit()

    # Auto-issue credential
    token = generate_credential_token(citizen)
    credential = Credential(
        citizen_id=citizen.id,
        token=token,
        credential_type='standard',
        expires_at=datetime.now(timezone.utc) + timedelta(days=365)
    )
    db.session.add(credential)
    db.session.commit()

    log_audit('citizen_verified', 'admin', current_user.id,
              'citizen', citizen.id, 'Identity verified and credential issued')
    flash(f'Citizen verified. Digital credential issued.', 'success')
    return redirect(url_for('enrollment_list'))


@app.route('/enrollment/<int:citizen_id>')
@login_required
def citizen_detail(citizen_id):
    citizen = db.session.get(Citizen, citizen_id)
    if not citizen:
        flash('Citizen not found.', 'error')
        return redirect(url_for('enrollment_list'))
    credentials = Credential.query.filter_by(citizen_id=citizen.id).all()
    consents = ConsentRecord.query.filter_by(citizen_id=citizen.id).all()
    qr_data = None
    if credentials:
        active = next((c for c in credentials if c.status == 'active'), None)
        if active:
            qr_data = generate_qr_code(active.token)
    return render_template('citizen_detail.html', citizen=citizen,
                           credentials=credentials, consents=consents, qr_data=qr_data)


# ─── Institutions ─────────────────────────────────────────

@app.route('/institutions')
@login_required
def institution_list():
    institutions = Institution.query.order_by(Institution.registered_at.desc()).all()
    return render_template('institutions.html', institutions=institutions)


@app.route('/institutions/new', methods=['GET', 'POST'])
@login_required
def institution_new():
    if request.method == 'POST':
        api_key = secrets.token_urlsafe(48)
        inst = Institution(
            name=request.form['name'].strip(),
            sector=request.form['sector'],
            api_key=api_key,
            contact_email=request.form.get('contact_email', '').strip()
        )
        db.session.add(inst)
        db.session.commit()
        log_audit('institution_registered', 'admin', current_user.id,
                  'institution', inst.id, f'{inst.name} ({inst.sector})')
        flash(f'Institution registered. API Key: {api_key}', 'success')
        return redirect(url_for('institution_list'))
    return render_template('institution_form.html', sectors=Config.SUPPORTED_SECTORS)


# ─── Verification Gateway ─────────────────────────────────

@app.route('/verifications')
@login_required
def verification_list():
    verifications = VerificationRequest.query.order_by(
        VerificationRequest.created_at.desc()
    ).all()
    return render_template('verifications.html', verifications=verifications)


@app.route('/verifications/<int:req_id>/approve', methods=['POST'])
@login_required
def approve_verification(req_id):
    vr = db.session.get(VerificationRequest, req_id)
    if not vr:
        flash('Verification request not found.', 'error')
        return redirect(url_for('verification_list'))

    citizen = Citizen.query.filter_by(national_id=vr.citizen_national_id).first()
    if not citizen or citizen.enrollment_status != 'verified':
        vr.status = 'denied'
        vr.resolved_at = datetime.now(timezone.utc)
        vr.response_data = json.dumps({'error': 'Citizen not verified'})
        db.session.commit()
        flash('Denied: citizen not found or not verified.', 'error')
        return redirect(url_for('verification_list'))

    # Build minimal response based on verification type
    response = {'status': 'verified', 'timestamp': datetime.now(timezone.utc).isoformat()}
    if vr.verification_type == 'identity':
        response['identity_valid'] = True
    elif vr.verification_type == 'age':
        age = (date.today() - citizen.date_of_birth).days // 365
        response['age_above_18'] = age >= 18
    elif vr.verification_type == 'tax_id':
        response['tax_id_matched'] = True
    elif vr.verification_type == 'kyc':
        response['kyc_passed'] = True
        response['name_verified'] = True

    vr.status = 'approved'
    vr.resolved_at = datetime.now(timezone.utc)
    vr.response_data = json.dumps(response)

    inst = db.session.get(Institution, vr.institution_id)
    if inst:
        inst.verification_count += 1

    db.session.commit()
    log_audit('verification_approved', 'admin', current_user.id,
              'verification', vr.id, f'Type: {vr.verification_type}')
    flash('Verification approved. Minimal response sent.', 'success')
    return redirect(url_for('verification_list'))


@app.route('/verifications/<int:req_id>/deny', methods=['POST'])
@login_required
def deny_verification(req_id):
    vr = db.session.get(VerificationRequest, req_id)
    if not vr:
        flash('Request not found.', 'error')
        return redirect(url_for('verification_list'))
    vr.status = 'denied'
    vr.resolved_at = datetime.now(timezone.utc)
    vr.response_data = json.dumps({'status': 'denied'})
    db.session.commit()
    log_audit('verification_denied', 'admin', current_user.id, 'verification', vr.id)
    flash('Verification denied.', 'warning')
    return redirect(url_for('verification_list'))


# ─── Consent Management ───────────────────────────────────

@app.route('/consent')
@login_required
def consent_list():
    records = ConsentRecord.query.order_by(ConsentRecord.granted_at.desc()).all()
    return render_template('consent.html', records=records)


@app.route('/consent/<int:record_id>/revoke', methods=['POST'])
@login_required
def revoke_consent(record_id):
    record = db.session.get(ConsentRecord, record_id)
    if not record:
        flash('Consent record not found.', 'error')
        return redirect(url_for('consent_list'))
    record.granted = False
    record.revoked_at = datetime.now(timezone.utc)
    db.session.commit()
    log_audit('consent_revoked', 'admin', current_user.id, 'consent', record.id)
    flash('Consent revoked.', 'success')
    return redirect(url_for('consent_list'))


# ─── Government Connectors ────────────────────────────────

@app.route('/connectors')
@login_required
def connector_list():
    connectors = GovernmentConnector.query.order_by(GovernmentConnector.registered_at.desc()).all()
    return render_template('connectors.html', connectors=connectors)


@app.route('/connectors/new', methods=['GET', 'POST'])
@login_required
def connector_new():
    if request.method == 'POST':
        conn = GovernmentConnector(
            name=request.form['name'].strip(),
            system_type=request.form['system_type'],
            endpoint_url=request.form.get('endpoint_url', '').strip(),
            api_key=secrets.token_urlsafe(32)
        )
        db.session.add(conn)
        db.session.commit()
        log_audit('connector_registered', 'admin', current_user.id,
                  'connector', conn.id, f'{conn.name} ({conn.system_type})')
        flash(f'Government connector "{conn.name}" registered.', 'success')
        return redirect(url_for('connector_list'))
    system_types = ['national_id', 'civil_registry', 'tax', 'immigration', 'voter', 'social_protection']
    return render_template('connector_form.html', system_types=system_types)


# ─── Audit Logs ────────────────────────────────────────────

@app.route('/audit')
@login_required
def audit_list():
    page = request.args.get('page', 1, type=int)
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    return render_template('audit.html', logs=logs)


# ─── Credentials ──────────────────────────────────────────

@app.route('/credentials')
@login_required
def credential_list():
    credentials = Credential.query.order_by(Credential.issued_at.desc()).all()
    return render_template('credentials.html', credentials=credentials)


@app.route('/credentials/<int:cred_id>/revoke', methods=['POST'])
@login_required
def revoke_credential(cred_id):
    cred = db.session.get(Credential, cred_id)
    if not cred:
        flash('Credential not found.', 'error')
        return redirect(url_for('credential_list'))
    cred.status = 'revoked'
    db.session.commit()
    log_audit('credential_revoked', 'admin', current_user.id, 'credential', cred.id)
    flash('Credential revoked.', 'success')
    return redirect(url_for('credential_list'))


# ─── Public API (for institutions) ────────────────────────

@app.route('/api/v1/verify', methods=['POST'])
def api_verify():
    """External API endpoint for institutions to submit verification requests."""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({'error': 'Missing API key'}), 401

    institution = Institution.query.filter_by(api_key=api_key, status='active').first()
    if not institution:
        return jsonify({'error': 'Invalid or inactive API key'}), 403

    data = request.get_json()
    if not data or 'national_id' not in data or 'verification_type' not in data:
        return jsonify({'error': 'Missing national_id or verification_type'}), 400

    valid_types = ['identity', 'age', 'tax_id', 'kyc', 'address', 'employment']
    if data['verification_type'] not in valid_types:
        return jsonify({'error': f'Invalid verification_type. Must be one of: {valid_types}'}), 400

    vr = VerificationRequest(
        institution_id=institution.id,
        citizen_national_id=data['national_id'],
        verification_type=data['verification_type'],
        request_fields=json.dumps(data.get('fields', [])),
        consent_required=data.get('consent_required', True)
    )
    db.session.add(vr)
    db.session.commit()

    log_audit('api_verification_request', 'institution', institution.id,
              'verification', vr.id,
              f'{institution.name} requested {data["verification_type"]} for {data["national_id"]}')

    # Auto-approve if citizen is verified and consent not required
    citizen = Citizen.query.filter_by(national_id=data['national_id']).first()
    if citizen and citizen.enrollment_status == 'verified' and not vr.consent_required:
        response = {'status': 'verified', 'timestamp': datetime.now(timezone.utc).isoformat()}
        if data['verification_type'] == 'identity':
            response['identity_valid'] = True
        elif data['verification_type'] == 'age':
            age = (date.today() - citizen.date_of_birth).days // 365
            response['age_above_18'] = age >= 18
        elif data['verification_type'] == 'tax_id':
            response['tax_id_matched'] = True
        elif data['verification_type'] == 'kyc':
            response['kyc_passed'] = True

        vr.status = 'approved'
        vr.resolved_at = datetime.now(timezone.utc)
        vr.response_data = json.dumps(response)
        institution.verification_count += 1
        db.session.commit()
        return jsonify({'request_id': vr.id, 'result': response}), 200

    return jsonify({
        'request_id': vr.id,
        'status': 'pending',
        'message': 'Verification request submitted. Awaiting consent/approval.'
    }), 202


@app.route('/api/v1/verify/<int:request_id>', methods=['GET'])
def api_verify_status(request_id):
    """Check status of a verification request."""
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({'error': 'Missing API key'}), 401

    institution = Institution.query.filter_by(api_key=api_key, status='active').first()
    if not institution:
        return jsonify({'error': 'Invalid API key'}), 403

    vr = VerificationRequest.query.filter_by(
        id=request_id, institution_id=institution.id
    ).first()
    if not vr:
        return jsonify({'error': 'Request not found'}), 404

    result = {'request_id': vr.id, 'status': vr.status}
    if vr.response_data:
        result['result'] = json.loads(vr.response_data)
    return jsonify(result), 200


@app.route('/api/v1/credential/validate', methods=['POST'])
def api_validate_credential():
    """Validate a citizen's digital credential token."""
    data = request.get_json()
    if not data or 'token' not in data:
        return jsonify({'error': 'Missing token'}), 400

    try:
        payload = jwt.decode(data['token'], app.config['JWT_SECRET'], algorithms=['HS256'])
        credential = Credential.query.filter_by(token=data['token'], status='active').first()
        if not credential:
            return jsonify({'valid': False, 'reason': 'Credential revoked or not found'}), 200

        credential.last_used_at = datetime.now(timezone.utc)
        credential.use_count += 1
        db.session.commit()

        return jsonify({
            'valid': True,
            'national_id': payload['sub'],
            'issued_at': payload['iat'],
            'expires_at': payload['exp']
        }), 200
    except jwt.ExpiredSignatureError:
        return jsonify({'valid': False, 'reason': 'Token expired'}), 200
    except jwt.InvalidTokenError:
        return jsonify({'valid': False, 'reason': 'Invalid token'}), 200


# ─── Citizen Self-Service Portal ───────────────────────────

@app.route('/portal')
def citizen_portal():
    """Public landing page for citizen self-service."""
    return render_template('portal/login.html')


@app.route('/portal/auth', methods=['POST'])
def citizen_auth():
    """Citizen authenticates with National ID + password (if set)."""
    national_id = request.form.get('national_id', '').strip()
    password = request.form.get('password', '').strip()
    citizen = Citizen.query.filter_by(national_id=national_id, enrollment_status='verified').first()
    if not citizen:
        flash('National ID not found or identity not yet verified.', 'error')
        return redirect(url_for('citizen_portal'))

    # If the citizen has a portal password set, require it. (Legacy
    # admin-enrolled citizens without a password can still log in by ID.)
    if citizen.password_hash:
        if not password or not citizen.check_password(password):
            flash('Invalid password.', 'error')
            return redirect(url_for('citizen_portal'))

    session['citizen_id'] = citizen.id
    log_audit('citizen_portal_login', 'citizen', citizen.id)
    return redirect(url_for('citizen_dashboard'))


# ─── Citizen Self Sign-Up ──────────────────────────────────

def _import_identities_from_sources(citizen, declared):
    """Mock-import identity records from affiliated authorities.

    In a real deployment this would call out to NIMC, INEC, FIRS, NHIS, etc.
    For the demo we accept whatever the citizen declares as already-issued
    record IDs and persist them as IdentityRecords.
    """
    created = []
    for category, cfg in Config.IDENTITY_CATEGORIES.items():
        record_id = (declared.get(category) or '').strip()
        if not record_id:
            continue
        rec = IdentityRecord(
            citizen_id=citizen.id,
            category=category,
            source=cfg['source'],
            record_id=record_id,
            record_data=json.dumps({
                'holder': f'{citizen.first_name} {citizen.last_name}',
                'category': category,
                'authority': cfg['affiliated_org'],
            }),
            verified=True,
            issued_at=datetime.now(timezone.utc),
        )
        db.session.add(rec)
        created.append(category)
    return created


@app.route('/portal/signup', methods=['GET', 'POST'])
def citizen_signup():
    """Self-service signup. Citizen declares which identities they already have
    (NIN, PVC, BVN, ...) and the gateway imports them from affiliated sources."""
    if request.method == 'POST':
        national_id = request.form.get('national_id', '').strip()
        password = request.form.get('password', '')
        if not national_id or len(password) < 6:
            flash('National ID and a password (min 6 chars) are required.', 'error')
            return redirect(url_for('citizen_signup'))
        if Citizen.query.filter_by(national_id=national_id).first():
            flash('A citizen with this National ID already exists. Please sign in.', 'error')
            return redirect(url_for('citizen_portal'))

        try:
            dob = datetime.strptime(request.form['date_of_birth'], '%Y-%m-%d').date()
        except (KeyError, ValueError):
            flash('Valid date of birth is required.', 'error')
            return redirect(url_for('citizen_signup'))

        citizen = Citizen(
            national_id=national_id,
            first_name=request.form.get('first_name', '').strip(),
            last_name=request.form.get('last_name', '').strip(),
            date_of_birth=dob,
            gender=request.form.get('gender', ''),
            email=request.form.get('email', '').strip(),
            phone=request.form.get('phone', '').strip(),
            address=request.form.get('address', '').strip(),
            enrollment_channel='self_signup',
            enrollment_status='verified',  # auto-verified once foundational ID present
            verified_at=datetime.now(timezone.utc),
            biometric_hash=secrets.token_hex(32),
        )
        citizen.set_password(password)
        db.session.add(citizen)
        db.session.flush()  # need citizen.id for FK

        # Import any identity records the citizen declares -- these would
        # normally be pulled from NIMC/INEC/FIRS/NHIS via federated connectors.
        declared = {cat: request.form.get(f'id_{cat}', '') for cat in Config.IDENTITY_CATEGORIES}
        imported = _import_identities_from_sources(citizen, declared)

        # Auto-issue master credential token
        token = generate_credential_token(citizen)
        cred = Credential(
            citizen_id=citizen.id,
            token=token,
            credential_type='master',
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        db.session.add(cred)
        db.session.commit()
        log_audit('citizen_self_signup', 'citizen', citizen.id,
                  details=f'Imported categories: {", ".join(imported) or "none"}')

        session['citizen_id'] = citizen.id
        flash(f'Welcome {citizen.first_name}. Your master token has been issued.', 'success')
        return redirect(url_for('citizen_dashboard'))

    return render_template('portal/signup.html', categories=Config.IDENTITY_CATEGORIES)


@app.route('/portal/dashboard')
def citizen_dashboard():
    """Citizen views their credentials, consent history, and can share credentials."""
    citizen_id = session.get('citizen_id')
    if not citizen_id:
        return redirect(url_for('citizen_portal'))

    citizen = db.session.get(Citizen, citizen_id)
    if not citizen:
        session.pop('citizen_id', None)
        return redirect(url_for('citizen_portal'))

    credentials = Credential.query.filter_by(citizen_id=citizen.id, status='active').all()
    consents = ConsentRecord.query.filter_by(citizen_id=citizen.id).all()
    pending_requests = VerificationRequest.query.filter_by(
        citizen_national_id=citizen.national_id, status='pending', consent_required=True
    ).all()

    # Identity completeness scoring + nudges
    held_categories = {r.category for r in
                       IdentityRecord.query.filter_by(citizen_id=citizen.id).all()}
    all_categories = Config.IDENTITY_CATEGORIES
    identity_status = []
    missing_nudges = []
    for cat, cfg in all_categories.items():
        present = cat in held_categories
        identity_status.append({
            'category': cat,
            'name': cfg['name'],
            'source': cfg['source'],
            'present': present,
            'affiliated_org': cfg['affiliated_org'],
        })
        if not present:
            missing_nudges.append({
                'category': cat,
                'message': f"Take some time to complete your {cfg['name']} info.",
                'cta': f"Upload to {cfg['affiliated_org']}",
                'sectors_blocked': cfg['required_sectors'],
            })
    completeness_pct = int(round(100 * len(held_categories) / max(1, len(all_categories))))

    # Full consent audit trail (all orgs that ever requested consent from this citizen)
    consent_audit = VerificationRequest.query.filter_by(
        citizen_national_id=citizen.national_id
    ).order_by(VerificationRequest.created_at.desc()).all()

    # Generate QR for master credential
    qr_data = None
    active_token = None
    if credentials:
        active_token = credentials[0].token
        qr_data = generate_qr_code(active_token)

    return render_template('portal/dashboard.html', citizen=citizen,
                           credentials=credentials, consents=consents,
                           pending_requests=pending_requests,
                           qr_data=qr_data, active_token=active_token,
                           identity_status=identity_status,
                           missing_nudges=missing_nudges,
                           completeness_pct=completeness_pct,
                           consent_audit=consent_audit)


@app.route('/portal/consent/approve/<int:req_id>', methods=['POST'])
def citizen_approve_consent(req_id):
    """Citizen approves a pending verification request."""
    citizen_id = session.get('citizen_id')
    if not citizen_id:
        return redirect(url_for('citizen_portal'))

    citizen = db.session.get(Citizen, citizen_id)
    vr = db.session.get(VerificationRequest, req_id)
    if not vr or vr.citizen_national_id != citizen.national_id or vr.status != 'pending':
        flash('Request not found or already processed.', 'error')
        return redirect(url_for('citizen_dashboard'))

    # Create consent record
    consent = ConsentRecord(
        citizen_id=citizen.id,
        institution_id=vr.institution_id,
        verification_request_id=vr.id,
        scope=f'{vr.verification_type} verification',
        granted=True,
        granted_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=90)
    )
    db.session.add(consent)

    # Build minimal response
    response = {'status': 'verified', 'timestamp': datetime.now(timezone.utc).isoformat()}
    if vr.verification_type == 'identity':
        response['identity_valid'] = True
    elif vr.verification_type == 'age':
        age = (date.today() - citizen.date_of_birth).days // 365
        response['age_above_18'] = age >= 18
    elif vr.verification_type == 'tax_id':
        response['tax_id_matched'] = True
    elif vr.verification_type == 'kyc':
        response['kyc_passed'] = True
        response['name_verified'] = True

    vr.status = 'approved'
    vr.resolved_at = datetime.now(timezone.utc)
    vr.response_data = json.dumps(response)

    inst = db.session.get(Institution, vr.institution_id)
    if inst:
        inst.verification_count += 1

    db.session.commit()
    log_audit('citizen_consent_granted', 'citizen', citizen.id,
              'verification', vr.id, f'Approved {vr.verification_type} for {inst.name if inst else "unknown"}')
    flash('Consent granted. The institution can now verify your identity.', 'success')
    return redirect(url_for('citizen_dashboard'))


@app.route('/portal/consent/deny/<int:req_id>', methods=['POST'])
def citizen_deny_consent(req_id):
    """Citizen denies a pending verification request."""
    citizen_id = session.get('citizen_id')
    if not citizen_id:
        return redirect(url_for('citizen_portal'))

    citizen = db.session.get(Citizen, citizen_id)
    vr = db.session.get(VerificationRequest, req_id)
    if not vr or vr.citizen_national_id != citizen.national_id or vr.status != 'pending':
        flash('Request not found or already processed.', 'error')
        return redirect(url_for('citizen_dashboard'))

    vr.status = 'denied'
    vr.resolved_at = datetime.now(timezone.utc)
    vr.response_data = json.dumps({'status': 'denied', 'reason': 'Citizen denied consent'})
    db.session.commit()
    log_audit('citizen_consent_denied', 'citizen', citizen.id, 'verification', vr.id)
    flash('Consent denied.', 'warning')
    return redirect(url_for('citizen_dashboard'))


@app.route('/portal/consent/revoke/<int:record_id>', methods=['POST'])
def citizen_revoke_consent(record_id):
    """Citizen revokes a previously granted consent."""
    citizen_id = session.get('citizen_id')
    if not citizen_id:
        return redirect(url_for('citizen_portal'))

    record = db.session.get(ConsentRecord, record_id)
    if not record or record.citizen_id != citizen_id:
        flash('Consent record not found.', 'error')
        return redirect(url_for('citizen_dashboard'))

    record.granted = False
    record.revoked_at = datetime.now(timezone.utc)
    db.session.commit()
    log_audit('citizen_consent_revoked', 'citizen', citizen_id, 'consent', record.id)
    flash('Consent revoked. The institution can no longer access your data.', 'success')
    return redirect(url_for('citizen_dashboard'))


@app.route('/portal/logout')
def citizen_logout():
    session.pop('citizen_id', None)
    return redirect(url_for('citizen_portal'))


# ─── 3-Factor Auth API (token + password + OTP) ──────────
# Used by institutions to authenticate a citizen with three factors:
#   1. Master credential token  -- something we issue
#   2. Citizen password         -- something the citizen knows
#   3. OTP delivered to SIM     -- something the citizen has

def _resolve_citizen_from_token(token):
    """Decode a master token and return the live Citizen record, or None."""
    try:
        payload = jwt.decode(token, app.config['JWT_SECRET'], algorithms=['HS256'])
    except jwt.PyJWTError:
        return None
    cred = Credential.query.filter_by(token=token, status='active').first()
    if not cred:
        return None
    return Citizen.query.filter_by(national_id=payload.get('sub')).first()


def _institution_from_request():
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return None
    return Institution.query.filter_by(api_key=api_key, status='active').first()


@app.route('/api/v1/auth/password', methods=['POST'])
def api_auth_password():
    """Factor 2: verify the citizen's portal password against a master token."""
    inst = _institution_from_request()
    if not inst:
        return jsonify({'error': 'Invalid or missing API key'}), 401
    data = request.get_json() or {}
    token = data.get('token', '')
    password = data.get('password', '')
    citizen = _resolve_citizen_from_token(token)
    if not citizen:
        return jsonify({'factor': 'password', 'verified': False,
                        'reason': 'Invalid master token'}), 200
    if not citizen.check_password(password):
        log_audit('3fa_password_failed', 'institution', inst.id,
                  'citizen', citizen.id)
        return jsonify({'factor': 'password', 'verified': False,
                        'reason': 'Password mismatch'}), 200
    log_audit('3fa_password_ok', 'institution', inst.id, 'citizen', citizen.id)
    return jsonify({'factor': 'password', 'verified': True,
                    'national_id': citizen.national_id}), 200


@app.route('/api/v1/auth/otp/request', methods=['POST'])
def api_auth_otp_request():
    """Factor 3 (step a): generate an OTP, 'send it to the citizen's SIM'.

    For the demo we just persist it and return it in the response so the
    institution demo can display it. In production this would push to an
    SMS gateway and the response would NOT include the code.
    """
    inst = _institution_from_request()
    if not inst:
        return jsonify({'error': 'Invalid or missing API key'}), 401
    data = request.get_json() or {}
    citizen = _resolve_citizen_from_token(data.get('token', ''))
    if not citizen:
        return jsonify({'error': 'Invalid master token'}), 400
    code = ''.join(secrets.choice('0123456789') for _ in range(6))
    otp = OTPCode(
        citizen_id=citizen.id,
        code=code,
        purpose=f'institution_auth:{inst.id}',
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=app.config.get('OTP_EXPIRY_MINUTES', 5)),
    )
    db.session.add(otp)
    db.session.commit()
    log_audit('3fa_otp_sent', 'institution', inst.id, 'citizen', citizen.id,
              f'OTP delivered to {citizen.phone or "registered SIM"}')
    return jsonify({
        'sent': True,
        'channel': 'sim',
        'masked_phone': (citizen.phone[:4] + '****' + citizen.phone[-2:]) if citizen.phone else 'SIM',
        'expires_in_minutes': app.config.get('OTP_EXPIRY_MINUTES', 5),
        'demo_code': code,  # demo only -- remove in production
    }), 200


@app.route('/api/v1/auth/otp/verify', methods=['POST'])
def api_auth_otp_verify():
    """Factor 3 (step b): verify a SIM OTP."""
    inst = _institution_from_request()
    if not inst:
        return jsonify({'error': 'Invalid or missing API key'}), 401
    data = request.get_json() or {}
    citizen = _resolve_citizen_from_token(data.get('token', ''))
    code = (data.get('code') or '').strip()
    if not citizen or not code:
        return jsonify({'factor': 'otp', 'verified': False,
                        'reason': 'Missing token or code'}), 200
    otp = OTPCode.query.filter_by(
        citizen_id=citizen.id, code=code, used=False,
        purpose=f'institution_auth:{inst.id}'
    ).order_by(OTPCode.id.desc()).first()
    now = datetime.now(timezone.utc)
    if not otp or otp.expires_at.replace(tzinfo=timezone.utc) < now:
        log_audit('3fa_otp_failed', 'institution', inst.id, 'citizen', citizen.id)
        return jsonify({'factor': 'otp', 'verified': False,
                        'reason': 'Invalid or expired OTP'}), 200
    otp.used = True
    db.session.commit()
    log_audit('3fa_otp_ok', 'institution', inst.id, 'citizen', citizen.id)
    return jsonify({'factor': 'otp', 'verified': True,
                    'national_id': citizen.national_id,
                    '3fa_complete': True}), 200


@app.route('/api/v1/verify/category', methods=['POST'])
def api_verify_category():
    """Category-aware verification.

    The institution declares which identity category it needs (e.g. 'health'
    for a hospital, 'banking' for a bank). If the citizen does not have a
    record in that category, the gateway returns `manual_kyc_required` so
    the institution falls back to its own onboarding flow -- and the citizen
    sees a nudge in their portal to complete that identity next time.
    """
    inst = _institution_from_request()
    if not inst:
        return jsonify({'error': 'Invalid or missing API key'}), 401
    data = request.get_json() or {}
    national_id = data.get('national_id', '')
    category = data.get('category', '')
    if category not in Config.IDENTITY_CATEGORIES:
        return jsonify({'error': f'Unknown category. Use one of: {list(Config.IDENTITY_CATEGORIES)}'}), 400
    citizen = Citizen.query.filter_by(national_id=national_id).first()
    if not citizen or citizen.enrollment_status != 'verified':
        return jsonify({'status': 'unknown_citizen',
                        'manual_kyc_required': True,
                        'reason': 'Citizen is not registered with FIG'}), 200

    record = IdentityRecord.query.filter_by(citizen_id=citizen.id, category=category).first()
    cat_cfg = Config.IDENTITY_CATEGORIES[category]
    log_audit('category_verify', 'institution', inst.id,
              'citizen', citizen.id, f'category={category} found={bool(record)}')
    if not record:
        return jsonify({
            'status': 'manual_kyc_required',
            'manual_kyc_required': True,
            'category': category,
            'reason': f'Citizen has no {cat_cfg["name"]} record on file',
            'nudge': f'Citizen should register {cat_cfg["name"]} with {cat_cfg["affiliated_org"]}',
        }), 200
    return jsonify({
        'status': 'verified',
        'manual_kyc_required': False,
        'category': category,
        'source': cat_cfg['source'],
        'record_id': record.record_id,
        'verified_at': datetime.now(timezone.utc).isoformat(),
    }), 200


# ─── Database Initialization ──────────────────────────────

def init_db():
    with app.app_context():
        db.create_all()

        # Create default admin if none exists
        if not AdminUser.query.first():
            admin = AdminUser(username='admin', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)

            # Seed demo government connectors
            demo_connectors = [
                GovernmentConnector(name='National Identity Database', system_type='national_id',
                                   endpoint_url='https://nid.gov.example/api', api_key=secrets.token_urlsafe(32)),
                GovernmentConnector(name='Civil Registry', system_type='civil_registry',
                                   endpoint_url='https://civil.gov.example/api', api_key=secrets.token_urlsafe(32)),
                GovernmentConnector(name='Tax Authority', system_type='tax',
                                   endpoint_url='https://tax.gov.example/api', api_key=secrets.token_urlsafe(32)),
                GovernmentConnector(name='Immigration Service', system_type='immigration',
                                   endpoint_url='https://immigration.gov.example/api', api_key=secrets.token_urlsafe(32)),
            ]
            for c in demo_connectors:
                db.session.add(c)

            # Seed demo institutions
            demo_institutions = [
                Institution(name='National Bank', sector='banking',
                            api_key=secrets.token_urlsafe(48), contact_email='api@nationalbank.example'),
                Institution(name='TelcoNet', sector='telecommunications',
                            api_key=secrets.token_urlsafe(48), contact_email='api@telconet.example'),
                Institution(name='Central Hospital', sector='healthcare',
                            api_key=secrets.token_urlsafe(48), contact_email='api@centralhospital.example'),
                Institution(name='Ministry of Education', sector='education',
                            api_key=secrets.token_urlsafe(48), contact_email='api@moe.gov.example'),
            ]
            for inst in demo_institutions:
                db.session.add(inst)

            db.session.commit()

            # Seed demo citizens with passwords + identity records
            demo_citizens = [
                {
                    'national_id': 'NID-2026-001',
                    'first_name': 'Ada', 'last_name': 'Okafor',
                    'date_of_birth': date(1995, 4, 12),
                    'gender': 'F', 'phone': '08031234567', 'email': 'ada@example.ng',
                    'password': 'demo1234',
                    'records': {  # citizen who has everything
                        'foundational': 'NIN-11122233344',
                        'voter': 'PVC-AOK001',
                        'tax': 'TIN-5566778',
                        'health': 'NHIS-AOK-9091',
                        'banking': 'BVN-22113344556',
                        'driving': 'FRSC-AOK-2023',
                    },
                },
                {
                    'national_id': 'NID-2026-002',
                    'first_name': 'Bola', 'last_name': 'Adeyemi',
                    'date_of_birth': date(1990, 9, 3),
                    'gender': 'M', 'phone': '08099887766', 'email': 'bola@example.ng',
                    'password': 'demo1234',
                    'records': {  # citizen MISSING health -> forced manual KYC at hospital
                        'foundational': 'NIN-99988877766',
                        'voter': 'PVC-BAD002',
                        'banking': 'BVN-77665544332',
                    },
                },
            ]
            for spec in demo_citizens:
                c = Citizen(
                    national_id=spec['national_id'],
                    first_name=spec['first_name'], last_name=spec['last_name'],
                    date_of_birth=spec['date_of_birth'], gender=spec['gender'],
                    phone=spec['phone'], email=spec['email'],
                    enrollment_channel='self_signup',
                    enrollment_status='verified',
                    verified_at=datetime.now(timezone.utc),
                    biometric_hash=secrets.token_hex(32),
                )
                c.set_password(spec['password'])
                db.session.add(c)
                db.session.flush()
                for cat, rid in spec['records'].items():
                    cfg = Config.IDENTITY_CATEGORIES[cat]
                    db.session.add(IdentityRecord(
                        citizen_id=c.id, category=cat, source=cfg['source'],
                        record_id=rid,
                        record_data=json.dumps({'holder': f'{c.first_name} {c.last_name}'}),
                        verified=True,
                        issued_at=datetime.now(timezone.utc),
                    ))
                # Issue master credential token
                token = generate_credential_token(c)
                db.session.add(Credential(
                    citizen_id=c.id, token=token, credential_type='master',
                    expires_at=datetime.now(timezone.utc) + timedelta(days=365),
                ))
            db.session.commit()
            log_audit('system_initialized', 'system', None, details='Database initialized with demo data')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
