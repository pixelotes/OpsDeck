"""
Tests for src/routes/disposal.py
Covers: list_disposals, disposal_detail, record_disposal, edit_disposal
"""
import pytest
from datetime import timedelta
from src import db
from src.utils.timezone_helper import today
from src.models import Asset, Peripheral, DisposalRecord, Brand, Supplier


def _brand(name):
    """Get-or-create a Brand by name (brand is now a relationship, not a string column)."""
    b = Brand.query.filter_by(name=name).first()
    if not b:
        b = Brand(name=name)
        db.session.add(b)
        db.session.flush()
    return b


def _supplier(name):
    """Get-or-create a Supplier by name (disposal partner is now an FK)."""
    s = Supplier.query.filter_by(name=name).first()
    if not s:
        s = Supplier(name=name)
        db.session.add(s)
        db.session.flush()
    return s


@pytest.fixture
def disposal_data(app):
    """Creates sample data for disposal testing."""
    with app.app_context():
        # Create asset with existing disposal record (for detail/edit tests)
        asset_with_disposal = Asset(
            name="Old Laptop",
            status="In Use",
            brand=_brand("Dell")
        )
        db.session.add(asset_with_disposal)
        db.session.commit()

        # Create asset WITHOUT disposal record (for new disposal test)
        asset_for_disposal = Asset(
            name="Asset For Disposal",
            status="In Use",
            brand=_brand("HP")
        )
        db.session.add(asset_for_disposal)
        db.session.commit()

        # Create peripheral to dispose
        peripheral = Peripheral(
            name="Broken Mouse",
            brand=_brand("Logitech")
        )
        db.session.add(peripheral)
        db.session.commit()

        # Suppliers used as disposal partners (free text replaced by FK)
        ewaste = _supplier("E-Waste Co")
        partner = _supplier("Refurb Shop")
        db.session.commit()

        # Create an existing disposal record for the first asset
        disposal = DisposalRecord(
            asset_id=asset_with_disposal.id,
            disposal_date=today() - timedelta(days=30),
            disposal_method="Recycled",
            disposal_partner_id=ewaste.id,
            notes="Recycled properly"
        )
        db.session.add(disposal)
        db.session.commit()

        yield {
            'asset_id': asset_with_disposal.id,
            'asset_for_disposal_id': asset_for_disposal.id,
            'peripheral_id': peripheral.id,
            'disposal_id': disposal.id,
            'supplier_id': ewaste.id,
            'partner_supplier_id': partner.id,
        }


# --- List Disposals ---

def test_list_disposals_loads(auth_client, disposal_data):
    """Test that disposal list page loads successfully."""
    response = auth_client.get('/disposal/')
    assert response.status_code == 200


def test_list_disposals_shows_records(auth_client, disposal_data):
    """Test that disposal list shows existing records."""
    response = auth_client.get('/disposal/')
    assert response.status_code == 200
    assert b'Recycled' in response.data or b'E-Waste' in response.data


# --- Disposal Detail ---

def test_disposal_detail_loads(auth_client, disposal_data):
    """Test that disposal detail page loads successfully."""
    response = auth_client.get(f'/disposal/{disposal_data["disposal_id"]}')
    assert response.status_code == 200


def test_disposal_detail_shows_info(auth_client, disposal_data):
    """Test that disposal detail shows disposal information."""
    response = auth_client.get(f'/disposal/{disposal_data["disposal_id"]}')
    assert response.status_code == 200
    assert b'E-Waste Co' in response.data or b'Recycled' in response.data


def test_disposal_detail_not_found(auth_client, disposal_data):
    """Test 404 for non-existent disposal record."""
    response = auth_client.get('/disposal/99999')
    assert response.status_code == 404


# --- Record Disposal ---

def test_record_disposal_form_loads_for_asset(auth_client, disposal_data):
    """Test that record disposal form loads for an asset."""
    response = auth_client.get(f'/disposal/record?asset_id={disposal_data["asset_id"]}')
    assert response.status_code == 200
    assert b'Old Laptop' in response.data


def test_record_disposal_form_loads_for_peripheral(auth_client, disposal_data):
    """Test that record disposal form loads for a peripheral."""
    response = auth_client.get(f'/disposal/record?peripheral_id={disposal_data["peripheral_id"]}')
    assert response.status_code == 200
    assert b'Broken Mouse' in response.data


def test_record_disposal_no_item_returns_error(auth_client, disposal_data):
    """Test that record disposal without item returns 400."""
    response = auth_client.get('/disposal/record')
    assert response.status_code == 400


def test_record_disposal_post_asset(auth_client, disposal_data, app):
    """Test recording disposal for an asset via POST."""
    data = {
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Donated',
        'disposal_partner_id': disposal_data['partner_supplier_id'],
        'notes': 'Donated to school'
    }
    response = auth_client.post(
        f'/disposal/record?asset_id={disposal_data["asset_for_disposal_id"]}',
        data=data,
        follow_redirects=True
    )
    assert response.status_code == 200

    with app.app_context():
        asset = db.session.get(Asset, disposal_data['asset_for_disposal_id'])
        assert asset.status == 'Disposed'
        assert asset.is_archived is True


def test_record_disposal_post_peripheral(auth_client, disposal_data, app):
    """Test recording disposal for a peripheral via POST."""
    data = {
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Destroyed',
        'disposal_partner_id': disposal_data['partner_supplier_id'],
        'notes': 'Securely destroyed'
    }
    response = auth_client.post(
        f'/disposal/record?peripheral_id={disposal_data["peripheral_id"]}',
        data=data,
        follow_redirects=True
    )
    assert response.status_code == 200

    with app.app_context():
        peripheral = db.session.get(Peripheral, disposal_data['peripheral_id'])
        assert peripheral.status == 'Disposed'
        assert peripheral.is_archived is True


# --- Edit Disposal ---

def test_edit_disposal_form_loads(auth_client, disposal_data):
    """Test that edit disposal form loads with existing data."""
    response = auth_client.get(f'/disposal/{disposal_data["disposal_id"]}/edit')
    assert response.status_code == 200
    assert b'E-Waste Co' in response.data or b'Recycled' in response.data


def test_edit_disposal_post_success(auth_client, disposal_data, app):
    """Test updating disposal record via POST."""
    data = {
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Resold',
        'disposal_partner_id': disposal_data['partner_supplier_id'],
        'notes': 'Updated notes',
        'reason': 'Correcting disposal method'
    }
    response = auth_client.post(
        f'/disposal/{disposal_data["disposal_id"]}/edit',
        data=data,
        follow_redirects=True
    )
    assert response.status_code == 200

    with app.app_context():
        record = db.session.get(DisposalRecord, disposal_data['disposal_id'])
        assert record.disposal_method == 'Resold'


def test_edit_disposal_requires_reason(auth_client, disposal_data):
    """Test that edit disposal requires a reason."""
    data = {
        'disposal_date': today().strftime('%Y-%m-%d'),
        'disposal_method': 'Resold',
        'disposal_partner_id': disposal_data['partner_supplier_id']
        # Missing 'reason'
    }
    response = auth_client.post(
        f'/disposal/{disposal_data["disposal_id"]}/edit',
        data=data
    )
    # Should return the form again with error
    assert response.status_code == 200
    assert b'reason' in response.data.lower() or b'required' in response.data.lower()


def test_edit_disposal_not_found(auth_client, disposal_data):
    """Test 404 when editing non-existent disposal."""
    response = auth_client.get('/disposal/99999/edit')
    assert response.status_code == 404
