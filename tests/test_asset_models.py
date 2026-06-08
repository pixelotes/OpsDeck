"""
Tests for src/routes/asset_models.py — standalone AssetModel management screen.
"""
import pytest
from src import db
from src.models.assets import Brand, AssetModel, Asset


@pytest.fixture
def brand_data(app):
    with app.app_context():
        brand = Brand(name="Dell")
        other = Brand(name="HP")
        db.session.add_all([brand, other])
        db.session.commit()
        return {'brand_id': brand.id, 'other_brand_id': other.id}


def test_list_models_loads(auth_client, brand_data):
    resp = auth_client.get('/asset-models/')
    assert resp.status_code == 200


def test_inline_create_model_form_post(auth_client, brand_data, app):
    """Inline picker posts multipart form WITHOUT notes; must not 415."""
    resp = auth_client.post(
        f'/brands/{brand_data["brand_id"]}/models/create',
        data={'name': 'Magic Mouse 2'},
        content_type='multipart/form-data',
        headers={'X-Requested-With': 'XMLHttpRequest'},
    )
    assert resp.status_code == 200
    assert resp.json['name'] == 'Magic Mouse 2'
    assert resp.json['existing'] is False
    with app.app_context():
        assert AssetModel.query.filter_by(name='Magic Mouse 2',
                                          brand_id=brand_data['brand_id']).count() == 1


def test_model_detail_lists_assets(auth_client, brand_data, app):
    with app.app_context():
        m = AssetModel(name='Latitude 5540', brand_id=brand_data['brand_id'])
        db.session.add(m)
        db.session.flush()
        asset = Asset(name='LT-001', status='In Use', brand_id=brand_data['brand_id'], model_id=m.id)
        db.session.add(asset)
        db.session.commit()
        mid = m.id
    resp = auth_client.get(f'/asset-models/{mid}')
    assert resp.status_code == 200
    assert b'Latitude 5540' in resp.data
    assert b'LT-001' in resp.data


def test_create_model(auth_client, brand_data, app):
    resp = auth_client.post('/asset-models/new', data={
        'name': 'XPS 13', 'brand_id': brand_data['brand_id'], 'notes': 'Ultrabook',
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        m = AssetModel.query.filter_by(name='XPS 13').first()
        assert m is not None
        assert m.brand_id == brand_data['brand_id']


def test_create_model_requires_brand(auth_client, brand_data, app):
    resp = auth_client.post('/asset-models/new', data={'name': 'No Brand Model'},
                            follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert AssetModel.query.filter_by(name='No Brand Model').first() is None


def test_duplicate_model_per_brand_blocked(auth_client, brand_data, app):
    data = {'name': 'Latitude', 'brand_id': brand_data['brand_id']}
    auth_client.post('/asset-models/new', data=data, follow_redirects=True)
    auth_client.post('/asset-models/new', data=data, follow_redirects=True)
    with app.app_context():
        assert AssetModel.query.filter_by(name='Latitude', brand_id=brand_data['brand_id']).count() == 1


def test_same_name_different_brand_allowed(auth_client, brand_data, app):
    auth_client.post('/asset-models/new', data={'name': 'Pro', 'brand_id': brand_data['brand_id']}, follow_redirects=True)
    auth_client.post('/asset-models/new', data={'name': 'Pro', 'brand_id': brand_data['other_brand_id']}, follow_redirects=True)
    with app.app_context():
        assert AssetModel.query.filter_by(name='Pro').count() == 2


def test_update_model(auth_client, brand_data, app):
    with app.app_context():
        m = AssetModel(name='Old', brand_id=brand_data['brand_id'])
        db.session.add(m)
        db.session.commit()
        mid = m.id
    resp = auth_client.post(f'/asset-models/{mid}/edit', data={
        'name': 'New', 'brand_id': brand_data['other_brand_id'],
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        m = db.session.get(AssetModel, mid)
        assert m.name == 'New'
        assert m.brand_id == brand_data['other_brand_id']


def test_delete_model(auth_client, brand_data, app):
    with app.app_context():
        m = AssetModel(name='Temp', brand_id=brand_data['brand_id'])
        db.session.add(m)
        db.session.commit()
        mid = m.id
    auth_client.post(f'/asset-models/{mid}/delete', follow_redirects=True)
    with app.app_context():
        assert db.session.get(AssetModel, mid) is None


def test_delete_model_in_use_blocked(auth_client, brand_data, app):
    with app.app_context():
        m = AssetModel(name='InUse', brand_id=brand_data['brand_id'])
        db.session.add(m)
        db.session.flush()
        asset = Asset(name='A1', status='In Use', brand_id=brand_data['brand_id'], model_id=m.id)
        db.session.add(asset)
        db.session.commit()
        mid = m.id
    auth_client.post(f'/asset-models/{mid}/delete', follow_redirects=True)
    with app.app_context():
        assert db.session.get(AssetModel, mid) is not None  # still there, in use
