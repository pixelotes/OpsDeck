"""Regression tests for the Certificate model expiry helpers.

`CertificateVersion.days_until_expiry` previously raised UnboundLocalError
because of `today = today()` shadowing the imported helper, which 500'd the
certificate list/detail pages.
"""
from datetime import timedelta
from src.models import db
from src.models.certificates import Certificate, CertificateVersion
from src.utils.timezone_helper import today


def _make_cert(name, days):
    cert = Certificate(name=name)
    db.session.add(cert)
    db.session.flush()
    version = CertificateVersion(
        certificate_id=cert.id,
        expires_at=today() + timedelta(days=days),
        is_active=True,
    )
    db.session.add(version)
    db.session.commit()
    return cert, version


def test_days_until_expiry_future(app, init_database):
    with app.app_context():
        cert, version = _make_cert('Future Cert', 10)
        assert version.days_until_expiry == 10
        assert cert.status_color == 'warning'  # 7 <= 10 < 30


def test_days_until_expiry_expired(app, init_database):
    with app.app_context():
        cert, version = _make_cert('Expired Cert', -3)
        assert version.days_until_expiry == -3
        assert cert.status_color == 'danger'


def test_days_until_expiry_healthy(app, init_database):
    with app.app_context():
        cert, version = _make_cert('Healthy Cert', 90)
        assert version.days_until_expiry == 90
        assert cert.status_color == 'success'
