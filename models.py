from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import bcrypt

db = SQLAlchemy()


class AdminUser(UserMixin, db.Model):
    """Admin users who manage the gateway."""
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='admin')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password):
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())


class Citizen(db.Model):
    """Enrolled citizens with verified identities."""
    __tablename__ = 'citizens'
    id = db.Column(db.Integer, primary_key=True)
    national_id = db.Column(db.String(20), unique=True, nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(10))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    biometric_hash = db.Column(db.String(256))
    password_hash = db.Column(db.String(128))  # for citizen self-service portal & 3FA
    enrollment_status = db.Column(db.String(20), default='pending')  # pending, verified, suspended
    enrollment_channel = db.Column(db.String(20), default='online')  # online, center, agent, self_signup
    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    verified_at = db.Column(db.DateTime)

    credentials = db.relationship('Credential', backref='citizen', lazy=True)
    consents = db.relationship('ConsentRecord', backref='citizen', lazy=True)
    identity_records = db.relationship('IdentityRecord', backref='citizen', lazy=True)

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def check_password(self, password):
        if not self.password_hash:
            return False
        return bcrypt.checkpw(password.encode(), self.password_hash.encode())


class Institution(db.Model):
    """Registered service providers (banks, telecoms, hospitals, etc.)."""
    __tablename__ = 'institutions'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sector = db.Column(db.String(50), nullable=False)
    api_key = db.Column(db.String(256), unique=True, nullable=False)
    status = db.Column(db.String(20), default='active')  # active, suspended, revoked
    contact_email = db.Column(db.String(120))
    registered_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    verification_count = db.Column(db.Integer, default=0)

    verification_requests = db.relationship('VerificationRequest', backref='institution', lazy=True)


class Credential(db.Model):
    """Reusable digital credentials issued to citizens."""
    __tablename__ = 'credentials'
    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey('citizens.id'), nullable=False)
    token = db.Column(db.String(512), unique=True, nullable=False)
    credential_type = db.Column(db.String(50), default='standard')  # standard, qr, verifiable_pass
    status = db.Column(db.String(20), default='active')  # active, expired, revoked
    issued_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime)
    last_used_at = db.Column(db.DateTime)
    use_count = db.Column(db.Integer, default=0)


class VerificationRequest(db.Model):
    """Identity verification requests from institutions."""
    __tablename__ = 'verification_requests'
    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey('institutions.id'), nullable=False)
    citizen_national_id = db.Column(db.String(20), nullable=False)
    verification_type = db.Column(db.String(50), nullable=False)  # identity, age, tax_id, etc.
    status = db.Column(db.String(20), default='pending')  # pending, approved, denied, expired
    request_fields = db.Column(db.Text)  # JSON of requested data fields
    response_data = db.Column(db.Text)  # JSON of minimal response
    consent_required = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime)


class ConsentRecord(db.Model):
    """Citizen consent for data sharing."""
    __tablename__ = 'consent_records'
    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey('citizens.id'), nullable=False)
    institution_id = db.Column(db.Integer, db.ForeignKey('institutions.id'), nullable=False)
    verification_request_id = db.Column(db.Integer, db.ForeignKey('verification_requests.id'))
    scope = db.Column(db.Text, nullable=False)  # what data is being shared
    granted = db.Column(db.Boolean, default=False)
    granted_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)

    institution = db.relationship('Institution', backref='consent_records')


class AuditLog(db.Model):
    """Immutable audit trail for all gateway operations."""
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    actor_type = db.Column(db.String(20))  # citizen, institution, admin, system
    actor_id = db.Column(db.String(50))
    target_type = db.Column(db.String(50))
    target_id = db.Column(db.String(50))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class IdentityRecord(db.Model):
    """A specific identity attribute imported from a government/affiliated source.

    e.g. National ID (NIN) from NIMC, Voter Card (PVC) from INEC,
    Health insurance from NHIS, etc. Used for identity completeness scoring
    and to determine whether a category-specific verification can be served.
    """
    __tablename__ = 'identity_records'
    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey('citizens.id'), nullable=False)
    category = db.Column(db.String(40), nullable=False)  # foundational, voter, tax, health, education, employment, banking, driving
    source = db.Column(db.String(80), nullable=False)    # NIMC, INEC, FIRS, NHIS, ...
    record_id = db.Column(db.String(80))                  # external record id (e.g. NIN number)
    record_data = db.Column(db.Text)                      # JSON of attributes
    verified = db.Column(db.Boolean, default=True)
    issued_at = db.Column(db.DateTime)
    imported_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class OTPCode(db.Model):
    """One-time codes sent to a citizen's SIM for the 3FA 'something you have' factor."""
    __tablename__ = 'otp_codes'
    id = db.Column(db.Integer, primary_key=True)
    citizen_id = db.Column(db.Integer, db.ForeignKey('citizens.id'), nullable=False)
    code = db.Column(db.String(10), nullable=False)
    purpose = db.Column(db.String(40), default='institution_auth')
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, nullable=False)


class GovernmentConnector(db.Model):
    """Registered government identity source systems."""
    __tablename__ = 'government_connectors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    system_type = db.Column(db.String(50), nullable=False)  # national_id, civil_registry, tax, immigration, voter, social_protection
    endpoint_url = db.Column(db.String(500))
    api_key = db.Column(db.String(256))
    status = db.Column(db.String(20), default='active')
    last_sync = db.Column(db.DateTime)
    registered_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
