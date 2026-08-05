
import pytest
from src.models import User, Subscription, OnboardingPack, ProcessItem, OnboardingProcess, OffboardingProcess, Supplier
from src import db
from datetime import datetime

class TestSubscriptionAccessFlow:

    @pytest.fixture
    def setup_data(self, app, init_database):
        db = init_database
        # Check if Admin exists (created by auth_client)
        admin = User.query.filter_by(email='admin@test.com').first()
        if not admin:
            admin = User(name='Admin', email='admin@test.com', role='admin')
            admin.set_password('password')
            db.session.add(admin)
        
        # Create Target User
        user = User(name='Employee', email='emp@test.com', role='user') 
        user.set_password('password')

        # Create Supplier (Required for Subscription)
        supplier = Supplier(name='Test Supplier')
        
        db.session.add(admin)
        db.session.add(user)
        db.session.add(supplier)
        db.session.commit()

        # Create Subscription
        subscription = Subscription(
            name='Test Subscription',
            subscription_type='SaaS',
            supplier_id=supplier.id,
            cost=100,
            currency='EUR',
            renewal_period_type='monthly',
            renewal_date=datetime.today().date()
        )
        db.session.add(subscription)
        db.session.commit()

        return {
            'admin': admin,
            'user': user,
            'subscription': subscription
        }

    def test_manual_access_management(self, auth_client, init_database, setup_data):
        """Test manually adding and removing users from subscription."""
        user = setup_data['user']
        subscription = setup_data['subscription']
        
        # 1. Add User
        response = auth_client.post(f'/subscriptions/{subscription.id}/users/add', data={
            'user_ids': user.id
        }, follow_redirects=True)
        assert response.status_code == 200
        assert f'Added {user.name}'.encode() in response.data
        
        # Verify DB
        db_sub = db.session.get(Subscription,subscription.id)
        assert user in db_sub.users

        # 2. Remove User
        response = auth_client.post(f'/subscriptions/{subscription.id}/users/remove/{user.id}', follow_redirects=True)
        assert response.status_code == 200
        assert f'User {user.name} removed'.encode() in response.data

        # Verify DB
        db_sub = db.session.get(Subscription,subscription.id)
        assert user not in db_sub.users

    def test_onboarding_integration(self, auth_client, init_database, setup_data):
        """Test onboarding flow with subscription pack item."""
        db = init_database
        subscription = setup_data['subscription']

        # 1. Create Pack with Subscription Item
        pack = OnboardingPack(name='Engineering Pack')
        db.session.add(pack)
        db.session.commit()

        # Add item to pack (Simulate what the form does)
        # We need to manually create PackItem or use the route. Let's use route for full integration?
        # Route is /packs/<id> POST. Easier to just create model directly here for speed.
        from src.models import PackItem
        pack_item = PackItem(
            pack_id=pack.id,
            item_type='Subscription',
            subscription_id=subscription.id,
            description=f'Propagate access to {subscription.name}'
        )
        db.session.add(pack_item)
        db.session.commit()

        # 2. Create Onboarding Process
        # We use the route logic simulation
        process = OnboardingProcess(
            new_hire_name='New Hire',
            start_date=datetime.today(),
            pack_id=pack.id,
            user_id=setup_data['user'].id # Link user immediately for testing simplicity
        )
        db.session.add(process)
        db.session.commit()

        # Generate Checklist Items (This happens in new_onboarding route usually)
        # We simulate the checklist generation logic for the Pack Item
        process_item = ProcessItem(
            onboarding_process_id=process.id,
            description=pack_item.description,
            item_type='Subscription',
            linked_object_id=subscription.id
        )
        db.session.add(process_item)
        db.session.commit()

        # 3. Execute "Add User" Action
        response = auth_client.post(f'/onboarding/process/{process.id}/add_to_subscription/{process_item.id}', follow_redirects=True)
        
        assert response.status_code == 200
        assert f'User {setup_data["user"].name} added to subscription'.encode() in response.data
        
        # Verify access granted
        assert setup_data['user'] in subscription.users
        
        # Verify item completed
        assert db.session.get(ProcessItem, process_item.id).is_completed == True

    def test_offboarding_integration(self, auth_client, init_database, setup_data):
        """Test offboarding flow revokes subscription access."""
        db = init_database
        user = setup_data['user']
        subscription = setup_data['subscription']

        # Setup: User has access
        subscription.users.append(user)
        db.session.commit()
        assert user in subscription.users

        # 1. Create Offboarding Process
        process = OffboardingProcess(
            user_id=user.id,
            departure_date=datetime.today()
        )
        db.session.add(process)
        db.session.commit()

        # 2. Generate Revocation Checklist Item (logic from new_offboarding)
        # Since user is in subscription.users, new_offboarding would generate an item.
        process_item = ProcessItem(
            offboarding_process_id=process.id,
            description=f"Revoke access to {subscription.name}",
            item_type='RevokeSubscriptionAccess',
            linked_object_id=subscription.id
        )
        db.session.add(process_item)
        db.session.commit()

        # 3. Execute "Revoke Access" Action
        response = auth_client.post(f'/onboarding/offboarding/{process.id}/revoke_subscription/{process_item.id}', follow_redirects=True)

        assert response.status_code == 200
        assert f'User removed from {subscription.name}'.encode() in response.data

        # Verify access revoked
        assert user not in subscription.users
        
        # Verify item completed
        assert db.session.get(ProcessItem, process_item.id).is_completed == True
