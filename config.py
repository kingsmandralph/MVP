import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'fig-gateway-dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///fig_gateway.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JWT_SECRET = os.environ.get('JWT_SECRET', 'fig-jwt-secret-change-in-production')
    JWT_EXPIRY_HOURS = 24
    GATEWAY_NAME = 'Federated National Digital Identity Gateway'
    SUPPORTED_SECTORS = [
        'banking', 'telecommunications', 'healthcare',
        'government', 'education', 'employment'
    ]
    OTP_EXPIRY_MINUTES = 5

    # Identity categories the gateway federates. Each maps to a real-world
    # affiliated authority. The "sectors" list says which institution sectors
    # *require* that category for KYC.
    IDENTITY_CATEGORIES = {
        'foundational': {
            'name': 'National ID (NIN)', 'source': 'NIMC',
            'affiliated_org': 'National Identity Management Commission',
            'required_sectors': ['banking', 'telecommunications', 'government', 'employment'],
        },
        'voter':        {
            'name': 'Voter Card (PVC)', 'source': 'INEC',
            'affiliated_org': 'Independent National Electoral Commission',
            'required_sectors': ['government'],
        },
        'tax':          {
            'name': 'Tax ID (TIN)', 'source': 'FIRS',
            'affiliated_org': 'Federal Inland Revenue Service',
            'required_sectors': ['banking', 'employment'],
        },
        'health':       {
            'name': 'Health Insurance (NHIS)', 'source': 'NHIS',
            'affiliated_org': 'National Health Insurance Scheme',
            'required_sectors': ['healthcare'],
        },
        'education':    {
            'name': 'Education Records', 'source': 'Ministry of Education',
            'affiliated_org': 'Federal Ministry of Education',
            'required_sectors': ['education'],
        },
        'employment':   {
            'name': 'Pension / Employment', 'source': 'PenCom',
            'affiliated_org': 'National Pension Commission',
            'required_sectors': ['employment'],
        },
        'banking':      {
            'name': 'Bank Verification (BVN)', 'source': 'CBN',
            'affiliated_org': 'Central Bank of Nigeria',
            'required_sectors': ['banking'],
        },
        'driving':      {
            'name': 'Driver License', 'source': 'FRSC',
            'affiliated_org': 'Federal Road Safety Corps',
            'required_sectors': ['government'],
        },
    }
