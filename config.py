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
