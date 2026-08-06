# src/models/finance.py
"""
Finance-related models for exchange rate management.
"""
from src.utils.timezone_helper import now
from ..extensions import db


class FinanceSettings(db.Model):
    """Configuration for the exchange rate provider."""
    __tablename__ = 'finance_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    api_provider = db.Column(db.String(50), default='frankfurter')
    api_endpoint = db.Column(db.String(255), default='https://api.frankfurter.app/latest')
    api_key = db.Column(db.String(255), nullable=True)  # Some providers require API key
    base_currency = db.Column(db.String(3), default='EUR')
    last_sync_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    @classmethod
    def get_settings(cls):
        """Get or create the singleton settings instance."""
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings


class ExchangeRate(db.Model):
    """Historical exchange rates."""
    __tablename__ = 'exchange_rate'
    
    id = db.Column(db.Integer, primary_key=True)
    currency_code = db.Column(db.String(3), nullable=False, index=True)
    rate = db.Column(db.Float, nullable=False)  # Value relative to base currency (EUR)
    fetched_at = db.Column(db.DateTime, default=lambda: now(), index=True)

    __table_args__ = (
        db.Index('idx_exchange_rate_currency_date', 'currency_code', 'fetched_at'),
    )

    @classmethod
    def get_latest_rate(cls, currency_code):
        """Get the most recent rate for a currency."""
        return cls.query.filter_by(currency_code=currency_code)\
            .order_by(cls.fetched_at.desc()).first()
