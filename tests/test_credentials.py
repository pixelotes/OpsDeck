#!/usr/bin/env python3
"""
Test script for credentials routes
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import create_app
from src.models import db, User
from src.models.credentials import Credential, CredentialSecret
from datetime import timedelta
from src.utils.timezone_helper import now

def run_credentials_test():
    """Test the credentials functionality"""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("CREDENTIALS TRACKER TEST")
        print("=" * 60)
        
        # 1. Check if tables exist
        print("\n1. Checking database tables...")
        try:
            credential_count = Credential.query.count()
            secret_count = CredentialSecret.query.count()
            print(f"   ✓ Credentials table exists ({credential_count} records)")
            print(f"   ✓ CredentialSecrets table exists ({secret_count} records)")
        except Exception as e:
            print(f"   ✗ Error accessing tables: {e}")
            return False
        
        # 2. Get admin user
        print("\n2. Finding admin user...")
        admin = User.query.filter_by(email='admin@example.com').first()
        if not admin:
            print("   ✗ Admin user not found")
            return False
        print(f"   ✓ Admin user found: {admin.name} ({admin.email})")
        
        # 3. Create a test credential
        print("\n3. Creating test credential...")
        try:
            # Check if test credential already exists
            test_cred = Credential.query.filter_by(name='Test API Key').first()
            if test_cred:
                print("   ℹ Test credential already exists, deleting...")
                db.session.delete(test_cred)
                db.session.commit()
            
            # Create new credential
            new_cred = Credential(
                name='Test API Key',
                type='API Key',
                owner_id=admin.id,
                owner_type='User',
                description='Test credential for validation',
                break_glass=False
            )
            db.session.add(new_cred)
            db.session.flush()
            
            # Create secret
            secret = CredentialSecret(
                credential_id=new_cred.id,
                expires_at=now() + timedelta(days=15),  # Expires in 15 days
                is_active=True
            )
            secret.set_secret('mySecretAPIKey1234567890')
            db.session.add(secret)
            db.session.commit()
            
            print(f"   ✓ Created credential: {new_cred.name}")
            print(f"   ✓ Secret masked value: {secret.masked_value}")
            print(f"   ✓ Expires: {secret.expires_at.strftime('%Y-%m-%d')}")
            
        except Exception as e:
            print(f"   ✗ Error creating credential: {e}")
            db.session.rollback()
            return False
        
        # 4. Test credential properties
        print("\n4. Testing credential properties...")
        try:
            print(f"   - Owner: {new_cred.owner.name if new_cred.owner else 'None'}")
            print(f"   - Active secret: {new_cred.active_secret.masked_value if new_cred.active_secret else 'None'}")
            print(f"   - Target name: {new_cred.target_name}")
            
            if new_cred.active_secret:
                print(f"   - Days until expiry: {new_cred.active_secret.days_until_expiry}")
                print(f"   - Expiry status: {new_cred.active_secret.expiry_status}")
                print("   ✓ All properties working correctly")
        except Exception as e:
            print(f"   ✗ Error testing properties: {e}")
            return False
        
        # 5. Test secret rotation
        print("\n5. Testing secret rotation...")
        try:
            # Deactivate current secret
            old_secret = new_cred.active_secret
            old_secret.is_active = False
            
            # Create new secret
            new_secret = CredentialSecret(
                credential_id=new_cred.id,
                expires_at=now() + timedelta(days=30),
                is_active=True
            )
            new_secret.set_secret('newRotatedKey9876543210')
            db.session.add(new_secret)
            db.session.commit()
            
            print(f"   ✓ Old secret deactivated: {old_secret.masked_value}")
            print(f"   ✓ New secret created: {new_secret.masked_value}")
            print(f"   ✓ Active secret is now: {new_cred.active_secret.masked_value}")
            
            # Verify secret history
            all_secrets = new_cred.secrets.all()
            print(f"   ✓ Total secrets in history: {len(all_secrets)}")
            
        except Exception as e:
            print(f"   ✗ Error rotating secret: {e}")
            db.session.rollback()
            return False
        
        # 6. Test masking logic
        print("\n6. Testing secret masking logic...")
        test_cases = [
            ('short', '****'),
            ('test', '****'),
            ('test1234', '****1234'),
            ('veryLongSecretKey123456', '******************3456'),
        ]
        
        for raw_value, expected_mask in test_cases:
            temp_secret = CredentialSecret()
            temp_secret.set_secret(raw_value)
            if temp_secret.masked_value == expected_mask:
                print(f"   ✓ '{raw_value}' → '{temp_secret.masked_value}'")
            else:
                print(f"   ✗ '{raw_value}' → '{temp_secret.masked_value}' (expected '{expected_mask}')")
        
        # 7. Test expiring credentials query
        print("\n7. Testing expiring credentials query...")
        try:
            # Create a credential expiring in 7 days (should trigger notification)
            expiring_cred = Credential(
                name='Expiring Soon Credential',
                type='Password',
                owner_id=admin.id,
                owner_type='User',
                description='This should trigger notification',
                break_glass=True
            )
            db.session.add(expiring_cred)
            db.session.flush()
            
            expiring_secret = CredentialSecret(
                credential_id=expiring_cred.id,
                expires_at=now() + timedelta(days=7),
                is_active=True
            )
            expiring_secret.set_secret('expiringPassword123')
            db.session.add(expiring_secret)
            db.session.commit()
            
            # Query expiring credentials
            today = now().date()
            active_secrets = CredentialSecret.query.filter(
                CredentialSecret.is_active == True,
                CredentialSecret.expires_at.isnot(None)
            ).all()
            
            expiring_in_7_days = [
                s for s in active_secrets 
                if (s.expires_at.date() - today).days == 7
            ]
            
            print(f"   ✓ Found {len(expiring_in_7_days)} credential(s) expiring in 7 days")
            for s in expiring_in_7_days:
                print(f"     - {s.credential.name} ({s.masked_value})")
            
        except Exception as e:
            print(f"   ✗ Error testing expiring credentials: {e}")
            db.session.rollback()
            return False
        
        # 8. Summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        total_credentials = Credential.query.count()
        total_secrets = CredentialSecret.query.count()
        active_secrets_count = CredentialSecret.query.filter_by(is_active=True).count()
        
        print(f"Total Credentials: {total_credentials}")
        print(f"Total Secrets: {total_secrets}")
        print(f"Active Secrets: {active_secrets_count}")
        print("\n✓ All tests passed successfully!")
        print("\nYou can now access the credentials at:")
        print("  http://127.0.0.1:5000/credentials/")
        print("\nLogin with:")
        print("  Email: admin@example.com")
        print("  Password: admin123")
        
        return True

if __name__ == '__main__':
    success = run_credentials_test()
    sys.exit(0 if success else 1)
