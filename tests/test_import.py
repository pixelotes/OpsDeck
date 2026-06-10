"""Tests for the admin bulk CSV import (users): template, preview, commit."""
import io
from src.models import db, User


def _upload(client, type_key, csv_bytes):
    return client.post(
        f'/admin/import/{type_key}/preview',
        data={'file': (io.BytesIO(csv_bytes), 'data.csv')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )


def test_template_download(auth_client):
    r = auth_client.get('/admin/import/users/template')
    assert r.status_code == 200
    assert 'text/csv' in r.content_type
    body = r.get_data(as_text=True)
    assert body.splitlines()[0] == 'name,email'


def test_preview_classifies_without_persisting(auth_client, app):
    with app.app_context():
        existing = User(name='Existing', email='dup@test.com', role='user')
        existing.set_password('x')
        db.session.add(existing)
        db.session.commit()
        before = User.query.count()

    csv = b'name,email\nNew Person,new@test.com\nDup,dup@test.com\nNoEmail,\n'
    r = _upload(auth_client, 'users', csv)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '1 to create' in body
    assert '1 skipped' in body
    assert '1 error' in body

    with app.app_context():
        assert User.query.count() == before  # preview must NOT create anything


def test_commit_creates_users(auth_client, app):
    csv_text = 'name,email\nAlice Imported,alice.imported@test.com\n'
    r = auth_client.post(
        '/admin/import/users/commit',
        data={'csv_text': csv_text},
        follow_redirects=True,
    )
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'alice.imported@test.com' in body  # password table shows the new user
    with app.app_context():
        u = User.query.filter_by(email='alice.imported@test.com').first()
        assert u is not None
        assert u.role == 'user'


def test_unknown_type_is_rejected(auth_client):
    r = auth_client.get('/admin/import/bogus/template', follow_redirects=True)
    assert r.status_code == 200
    assert 'Unknown import type' in r.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# Service-level tests for the other importable types
# --------------------------------------------------------------------------- #
from src.services import import_service as imp  # noqa: E402


def test_every_importer_template_matches_columns(app, init_database):
    with app.app_context():
        for key, cfg in imp.IMPORTERS.items():
            header = imp.template_csv(key).splitlines()[0].split(',')
            assert header == cfg['required'] + cfg.get('optional', []), key


def test_suppliers_preview_and_commit(app, init_database):
    with app.app_context():
        from src.models import Supplier
        csv_text = 'name,email\nAcme Corp,sales@acme.com\nAcme Corp,dup@acme.com\n'
        prev = imp.process('suppliers', csv_text, commit=False)
        assert prev['counts'] == {'create': 1, 'skip': 1, 'error': 0}
        assert Supplier.query.count() == 0  # preview persists nothing
        res = imp.process('suppliers', csv_text, commit=True)
        assert res['counts']['create'] == 1
        assert Supplier.query.filter_by(name='Acme Corp').count() == 1


def test_assets_autocreate_dependencies(app, init_database):
    with app.app_context():
        from src.models import Asset, Location
        from src.models.assets import Brand, AssetModel
        res = imp.process('assets', 'name,serial_number,brand,model,location_name\nLaptop 1,SN-1,Dell,XPS 13,HQ\n', commit=True)
        assert res['counts']['create'] == 1
        assert Asset.query.filter_by(name='Laptop 1').first() is not None
        assert Brand.query.filter_by(name='Dell').first() is not None
        assert AssetModel.query.filter_by(name='XPS 13').first() is not None
        assert Location.query.filter_by(name='HQ').first() is not None


def test_subscriptions_require_existing_supplier(app, init_database):
    with app.app_context():
        from src.models import db, Supplier, Subscription
        prev = imp.process('subscriptions', 'supplier_name,name\nGhost Co,Sub\n', commit=False)
        assert prev['counts']['skip'] == 1 and prev['counts']['create'] == 0
        db.session.add(Supplier(name='Adobe', compliance_status='Pending'))
        db.session.commit()
        res = imp.process('subscriptions',
                          'supplier_name,name,cost,renewal_date\nAdobe,Creative Cloud,100,2026-01-01\n',
                          commit=True)
        assert res['counts']['create'] == 1
        assert Subscription.query.filter_by(name='Creative Cloud').first() is not None


def test_risks_with_comma_separated_categories(app, init_database):
    with app.app_context():
        from src.models import Risk, RiskCategory
        # category field quoted because it contains a comma
        res = imp.process('risks', 'name,likelihood,impact,category\nBreach,3,5,"Security,Compliance"\n', commit=True)
        assert res['counts']['create'] == 1
        risk = Risk.query.filter_by(risk_description='Breach').first()
        assert risk is not None and risk.inherent_impact == 5
        cats = {c.category for c in RiskCategory.query.filter_by(risk_id=risk.id).all()}
        assert cats == {'Security', 'Compliance'}


def test_missing_required_column_raises(app, init_database):
    import pytest
    with app.app_context():
        with pytest.raises(ValueError):
            imp.process('users', 'fullname,mail\nx,y\n', commit=False)
