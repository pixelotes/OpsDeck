import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.extensions import db
from src.models.security import Risk
from src.models.auth import User
from src.models.assets import Asset
from src import create_app
from datetime import date, timedelta

app = create_app()

with app.app_context():
    print("1. Resetting Database (Dropping Risk table to force schema update)...")
    # In a real prod env we would use migrations, but user authorized data loss/reset
    try:
        db.session.execute(db.text('DROP TABLE IF EXISTS risk_assets'))
        db.session.execute(db.text('DROP TABLE IF EXISTS risk'))
        db.create_all()
        print("   Database schema updated.")
    except Exception as e:
        print(f"   Error updating schema: {e}")

    print("\n2. Creating Test Data...")
    # Create User
    user = User.query.first()
    if not user:
        user = User(name="Test User", email="test@example.com")
        db.session.add(user)
        db.session.commit()
    
    # Create Asset
    asset = Asset.query.first()
    if not asset:
        asset = Asset(name="Test Server", status="In Use")
        db.session.add(asset)
        db.session.commit()

    print("\n3. Testing Risk Model...")
    risk = Risk(
        risk_description="Test Risk",
        owner_id=user.id,
        inherent_impact=4,
        inherent_likelihood=5,
        residual_impact=2,
        residual_likelihood=3,
        treatment_strategy="Mitigate",
        next_review_date=date.today() + timedelta(days=30)
    )
    
    # Test Relationships
    risk.assets.append(asset)
    
    db.session.add(risk)
    db.session.commit()
    
    print(f"   Risk Created: ID {risk.id}")
    print(f"   Inherent Score: {risk.inherent_score} (Expected 20)")
    print(f"   Residual Score: {risk.residual_score} (Expected 6)")
    print(f"   Criticality: {risk.criticality_level} (Expected Medium)")
    print(f"   Assets: {[a.name for a in risk.assets]}")
    print(f"   Owner: {risk.owner.name}")
    
    assert risk.inherent_score == 20
    assert risk.residual_score == 6
    assert risk.criticality_level == 'Medium'
    assert len(risk.assets.all()) == 1
    assert risk.assets[0].name == "Test Server"
    
    print("\nSUCCESS: Risk Model verification passed.")
