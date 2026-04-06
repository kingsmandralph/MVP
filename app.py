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
    VerificationRequest, ConsentRecord, AuditLog, GovernmentConnector
)

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)
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
    """Citizen authenticates with National ID to access their portal."""
    national_id = request.form.get('national_id', '').strip()
    citizen = Citizen.query.filter_by(national_id=national_id, enrollment_status='verified').first()
    if not citizen:
        flash('National ID not found or identity not yet verified.', 'error')
        return redirect(url_for('citizen_portal'))

    session['citizen_id'] = citizen.id
    return redirect(url_for('citizen_dashboard'))


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

    # Generate QR for active credential
    qr_data = None
    active_token = None
    if credentials:
        active_token = credentials[0].token
        qr_data = generate_qr_code(active_token)

    return render_template('portal/dashboard.html', citizen=citizen,
                           credentials=credentials, consents=consents,
                           pending_requests=pending_requests,
                           qr_data=qr_data, active_token=active_token)


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
            log_audit('system_initialized', 'system', None, details='Database initialized with demo data')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
