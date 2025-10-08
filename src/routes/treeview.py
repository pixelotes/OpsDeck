from flask import (
    Blueprint, render_template, request, url_for
)
from ..models import Location, User, Supplier
from .main import login_required

treeview_bp = Blueprint('treeview', __name__)

@treeview_bp.route('/')
@login_required
def tree_view():
    selected_root = request.args.get('root', 'locations')
    tree_data = []
    
    # Define the available options for the dropdown
    root_options = ["Locations", "Users", "Suppliers"]

    if selected_root == 'locations':
        locations = Location.query.order_by(Location.name).all()
        for location in locations:
            location_node = {
                'name': location.name,
                'icon': 'fa-map-marker-alt',
                'url': url_for('locations.location_detail', id=location.id),
                'children': []
            }
            for asset in location.assets:
                asset_node = {
                    'name': asset.name,
                    'icon': 'fa-laptop',
                    'url': url_for('assets.asset_detail', id=asset.id),
                    'children': []
                }
                for peripheral in asset.peripherals:
                    peripheral_node = {
                        'name': peripheral.name,
                        'icon': 'fa-keyboard',
                        'url': url_for('peripherals.edit_peripheral', id=peripheral.id)
                    }
                    asset_node['children'].append(peripheral_node)
                location_node['children'].append(asset_node)
            tree_data.append(location_node)

    elif selected_root == 'users':
        users = User.query.order_by(User.name).all()
        for user in users:
            user_node = {
                'name': user.name,
                'icon': 'fa-user',
                'url': url_for('users.user_detail', id=user.id),
                'children': []
            }
            # Add assigned assets as children
            if user.assets:
                assets_node = {'name': 'Assets', 'icon': 'fa-laptop', 'children': []}
                for asset in user.assets:
                    assets_node['children'].append({
                        'name': asset.name,
                        'icon': 'fa-laptop',
                        'url': url_for('assets.asset_detail', id=asset.id)
                    })
                user_node['children'].append(assets_node)
            
            # Add associated purchases as children
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

    elif selected_root == 'suppliers':
        suppliers = Supplier.query.order_by(Supplier.name).all()
        for supplier in suppliers:
            supplier_node = {
                'name': supplier.name,
                'icon': 'fa-building',
                'url': url_for('suppliers.supplier_detail', id=supplier.id),
                'children': []
            }
            # Add associated services
            if supplier.services:
                services_node = {'name': 'Services', 'icon': 'fa-cogs', 'children': []}
                for service in supplier.services:
                    services_node['children'].append({
                        'name': service.name,
                        'icon': 'fa-cogs',
                        'url': url_for('services.service_detail', id=service.id)
                    })
                supplier_node['children'].append(services_node)

            # Add associated assets
            if supplier.assets:
                assets_node = {'name': 'Assets', 'icon': 'fa-laptop', 'children': []}
                for asset in supplier.assets:
                    assets_node['children'].append({
                        'name': asset.name,
                        'icon': 'fa-laptop',
                        'url': url_for('assets.asset_detail', id=asset.id)
                    })
                supplier_node['children'].append(assets_node)
            tree_data.append(supplier_node)

    return render_template('tree_view.html',
                           tree_data=tree_data,
                           root_options=root_options,
                           selected_root=selected_root)