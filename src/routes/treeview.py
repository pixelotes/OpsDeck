from flask import (
    Blueprint, render_template, request, url_for
)
# --- UPDATED: Import Asset, Peripheral, License ---
from ..models import Location, User, Supplier, Asset, Peripheral
from .main import login_required

treeview_bp = Blueprint('treeview', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
ASSET_DETAIL = 'assets.asset_detail'
PERIPHERAL_DETAIL = 'peripherals.peripheral_detail'

@treeview_bp.route('/', methods=['GET'])
@login_required
def tree_view():
    selected_root = request.args.get('root', 'locations')
    tree_data = []

    # Define the available options for the dropdown
    root_options = ["Locations", "Users", "Remote", "Suppliers"]

    if selected_root == 'locations':
        locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()
        for location in locations:
            location_node = {
                'name': location.name,
                'icon': 'fa-map-marker-alt',
                'url': url_for('locations.location_detail', id=location.id),
                'children': []
            }
            # Show assets that have this location_id (physically present here)
            for asset in location.assets:
                if asset.is_archived:
                    continue
                asset_name = asset.name
                if asset.user:
                    asset_name += f" (assigned to {asset.user.name})"
                asset_node = {
                    'name': asset_name,
                    'icon': 'fa-laptop',
                    'url': url_for(ASSET_DETAIL, id=asset.id),
                    'children': []
                }
                for peripheral in asset.peripherals:
                    if peripheral.is_archived:
                        continue
                    peripheral_node = {
                        'name': peripheral.name,
                        'icon': 'fa-keyboard',
                        'url': url_for(PERIPHERAL_DETAIL, id=peripheral.id)
                    }
                    asset_node['children'].append(peripheral_node)
                location_node['children'].append(asset_node)
            tree_data.append(location_node)

    elif selected_root == 'users':
        users = User.query.order_by(User.name).filter_by(is_archived=False).all() # Show all users, even archived ones
        for user in users:
            user_node = {
                'name': user.name,
                'icon': 'fa-user',
                'url': url_for('users.user_detail', id=user.id),
                'children': []
            }
            # Add assigned assets
            if user.assets:
                assets_node = {'name': 'Assets', 'icon': 'fa-laptop', 'children': []}
                for asset in user.assets:
                    assets_node['children'].append({
                        'name': asset.name,
                        'icon': 'fa-laptop',
                        'url': url_for(ASSET_DETAIL, id=asset.id)
                    })
                user_node['children'].append(assets_node)

            # --- ADD Peripherals ---
            if user.peripherals:
                peripherals_node = {'name': 'Peripherals', 'icon': 'fa-keyboard', 'children': []}
                for peripheral in user.peripherals:
                    peripherals_node['children'].append({
                        'name': peripheral.name,
                        'icon': 'fa-keyboard', # Or fa-mouse, fa-headphones etc. based on type?
                        'url': url_for(PERIPHERAL_DETAIL, id=peripheral.id)
                    })
                user_node['children'].append(peripherals_node)
            # --- END ADD Peripherals ---

            # --- ADD Licenses ---
            if user.licenses:
                licenses_node = {'name': 'Licenses', 'icon': 'fa-id-badge', 'children': []}
                for license in user.licenses:
                    license_display_name = f"{license.name}"
                    # Example: Truncate key if you want to show part of it
                    # if license.license_key:
                    #    license_display_name += f" (...{license.license_key[-6:]})"

                    licenses_node['children'].append({
                        'name': license_display_name,
                        'icon': 'fa-id-badge', # Or fa-key
                        'url': url_for('licenses.detail', id=license.id)
                    })
                user_node['children'].append(licenses_node)
            # --- END ADD Licenses ---

            # Add associated purchases
            if user.purchases:
                purchases_node = {'name': 'Purchases', 'icon': 'fa-shopping-cart', 'children': []}
                for purchase in user.purchases:
                    purchases_node['children'].append({
                        'name': purchase.description,
                        'icon': 'fa-shopping-cart',
                        'url': url_for('purchases.purchase_detail', id=purchase.id)
                    })
                user_node['children'].append(purchases_node)
            tree_data.append(user_node)

    elif selected_root == 'remote':
        # Personal / Remote: Users as logical locations for assets with no physical location
        users_with_remote_assets = User.query.filter_by(is_archived=False).order_by(User.name).all()
        for user in users_with_remote_assets:
            # Filter to only remote assets (location_id is None)
            remote_assets = [a for a in user.assets if a.location_id is None and not a.is_archived]
            if not remote_assets:
                continue
            
            user_node = {
                'name': f"🏠 {user.name}",
                'icon': 'fa-user',
                'url': url_for('users.user_detail', id=user.id),
                'children': []
            }
            
            for asset in remote_assets:
                asset_node = {
                    'name': asset.name,
                    'icon': 'fa-laptop-house',  # Remote work icon
                    'url': url_for(ASSET_DETAIL, id=asset.id),
                    'children': []
                }
                # Also show peripherals attached to this remote asset
                for peripheral in asset.peripherals:
                    if peripheral.is_archived:
                        continue
                    peripheral_node = {
                        'name': peripheral.name,
                        'icon': 'fa-keyboard',
                        'url': url_for(PERIPHERAL_DETAIL, id=peripheral.id)
                    }
                    asset_node['children'].append(peripheral_node)
                user_node['children'].append(asset_node)
            
            tree_data.append(user_node)

    elif selected_root == 'suppliers':
        suppliers = Supplier.query.order_by(Supplier.name).all()
        for supplier in suppliers:
            supplier_node = {
                'name': supplier.name,
                'icon': 'fa-building',
                'url': url_for('suppliers.supplier_detail', id=supplier.id),
                'children': []
            }
            # Add associated subscriptions
            if supplier.subscriptions:
                subscriptions_node = {'name': 'Subscriptions', 'icon': 'fa-cogs', 'children': []}
                for subscription in supplier.subscriptions:
                    subscriptions_node['children'].append({
                        'name': subscription.name,
                        'icon': 'fa-cogs',
                        'url': url_for('subscriptions.subscription_detail', id=subscription.id)
                    })
                supplier_node['children'].append(subscriptions_node)

            # Add associated assets
            if supplier.assets:
                assets_node = {'name': 'Assets', 'icon': 'fa-laptop', 'children': []}
                for asset in supplier.assets:
                    assets_node['children'].append({
                        'name': asset.name,
                        'icon': 'fa-laptop',
                        'url': url_for(ASSET_DETAIL, id=asset.id)
                    })
                supplier_node['children'].append(assets_node)

            # --- ADD Peripherals ---
            if supplier.peripherals:
                peripherals_node = {'name': 'Peripherals', 'icon': 'fa-keyboard', 'children': []}
                for peripheral in supplier.peripherals:
                    peripherals_node['children'].append({
                        'name': peripheral.name,
                        'icon': 'fa-keyboard', # Or other icons based on type
                        'url': url_for(PERIPHERAL_DETAIL, id=peripheral.id)
                    })
                supplier_node['children'].append(peripherals_node)
            # --- END ADD Peripherals ---

            tree_data.append(supplier_node)

    return render_template('tree_view.html',
                           tree_data=tree_data,
                           root_options=root_options,
                           selected_root=selected_root)