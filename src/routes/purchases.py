from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import datetime
from ..models import db, Purchase, Supplier, User, PaymentMethod, Tag, Budget, PurchaseCostHistory
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now


purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')

@purchases_bp.route('/', methods=['GET'])
@login_required
@requires_permission('finance', access_level='READ_ONLY')
def purchases():
    all_purchases = Purchase.query.order_by(Purchase.purchase_date.desc()).all()
    return render_template('purchases/list.html', purchases=all_purchases)

@purchases_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission('finance', access_level='READ_ONLY')
def purchase_detail(id):
    purchase = db.get_or_404(Purchase, id)
    return render_template('purchases/detail.html', purchase=purchase)

@purchases_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('finance', access_level='READ_ONLY')
def new_purchase():
    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission('finance'):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for('purchases.purchases'))
        purchase_date = datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None
        
        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(purchase_date):
                flash('Error: This purchase date is outside the selected Budget\'s validity period.', 'danger')
                return render_template('purchases/form.html',
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        users=User.query.order_by(User.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        budgets=Budget.query.order_by(Budget.name).all())
        
        purchase = Purchase(
            internal_id=request.form.get('internal_id'),
            description=request.form['description'],
            invoice_number=request.form.get('invoice_number'),
            purchase_date=purchase_date,
            comments=request.form.get('comments'),
            supplier_id=request.form.get('supplier_id') or None,
            payment_method_id=request.form.get('payment_method_id') or None,
            budget_id=budget_id
        )
        db.session.add(purchase)
        db.session.commit()
        flash('Purchase created successfully!', 'success')
        return redirect(url_for('purchases.purchases'))

    return render_template('purchases/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

@purchases_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission('finance', access_level='READ_ONLY')
def edit_purchase(id):
    purchase = db.get_or_404(Purchase, id)
    if request.method == 'POST':
        # Manual check for WRITE access
        if not has_write_permission('finance'):
            flash('Write access required for this action.', 'danger')
            return redirect(url_for('purchases.purchase_detail', id=id))
        purchase_date = datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date()
        budget_id = request.form.get('budget_id') or None
        
        # Validate budget validity period if budget is selected
        if budget_id:
            budget = db.session.get(Budget,budget_id)
            if budget and not budget.is_active(purchase_date):
                flash('Error: This purchase date is outside the selected Budget\'s validity period.', 'danger')
                return render_template('purchases/form.html',
                                        purchase=purchase,
                                        suppliers=Supplier.query.order_by(Supplier.name).all(),
                                        users=User.query.order_by(User.name).all(),
                                        payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                                        tags=Tag.query.order_by(Tag.name).all(),
                                        budgets=Budget.query.order_by(Budget.name).all())
        
        purchase.internal_id = request.form.get('internal_id')
        purchase.description = request.form['description']
        purchase.invoice_number = request.form.get('invoice_number')
        purchase.purchase_date = purchase_date
        purchase.comments = request.form.get('comments')
        purchase.supplier_id = request.form.get('supplier_id') or None
        purchase.payment_method_id = request.form.get('payment_method_id') or None
        purchase.budget_id = budget_id
        db.session.commit()
        flash('Purchase updated successfully!', 'success')
        return redirect(url_for('purchases.purchases'))

    return render_template('purchases/form.html',
                            purchase=purchase,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

@purchases_bp.route('/<int:id>/approve', methods=['POST'])
@login_required
@requires_permission('finance')
def approve_purchase(id):
    if not has_write_permission('finance'):
        flash('Write access required to approve purchases.', 'danger')
        return redirect(url_for('purchases.purchase_detail', id=id))
    purchase = db.get_or_404(Purchase, id)
    user_id = session.get('user_id')
    purchase.validated_cost = purchase.calculated_cost
    purchase.cost_validated_at = now()
    purchase.cost_validated_by_id = user_id
    history_log = PurchaseCostHistory(
        purchase_id=id, action='Validated', cost=purchase.validated_cost, user_id=user_id
    )
    db.session.add(history_log)
    db.session.commit()
    flash(f'The cost for this purchase has been validated at EUR {purchase.validated_cost:.2f}.', 'success')
    return redirect(url_for('purchases.purchase_detail', id=id))

@purchases_bp.route('/<int:id>/unvalidate_cost', methods=['POST'])
@login_required
@requires_permission('finance')
def unvalidate_cost(id):
    if not has_write_permission('finance'):
        flash('Write access required to unvalidate costs.', 'danger')
        return redirect(url_for('purchases.purchase_detail', id=id))
    purchase = db.get_or_404(Purchase, id)
    user_id = session.get('user_id')
    history_log = PurchaseCostHistory(
        purchase_id=id, action='Un-validated', cost=purchase.validated_cost, user_id=user_id
    )
    db.session.add(history_log)
    purchase.validated_cost = None
    purchase.cost_validated_at = None
    purchase.cost_validated_by_id = None
    db.session.commit()
    flash('The validated cost has been removed. The cost will now be calculated dynamically.', 'info')
    return redirect(url_for('purchases.purchase_detail', id=id))