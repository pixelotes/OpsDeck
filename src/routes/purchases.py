from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session
)
from datetime import datetime
from ..models import db, Purchase, Supplier, User, PaymentMethod, Tag, Budget, PurchaseCostHistory
from .main import login_required

purchases_bp = Blueprint('purchases', __name__, url_prefix='/purchases')

@purchases_bp.route('/')
@login_required
def purchases():
    all_purchases = Purchase.query.order_by(Purchase.purchase_date.desc()).all()
    return render_template('purchases/list.html', purchases=all_purchases)

@purchases_bp.route('/<int:id>')
@login_required
def purchase_detail(id):
    purchase = Purchase.query.get_or_404(id)
    return render_template('purchases/detail.html', purchase=purchase)

@purchases_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_purchase():
    if request.method == 'POST':
        purchase = Purchase(
            internal_id=request.form.get('internal_id'),
            description=request.form['description'],
            invoice_number=request.form.get('invoice_number'),
            purchase_date=datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date(),
            comments=request.form.get('comments'),
            supplier_id=request.form.get('supplier_id') or None,
            payment_method_id=request.form.get('payment_method_id') or None,
            budget_id=request.form.get('budget_id') or None
        )
        db.session.add(purchase)
        db.session.commit()
        flash('Purchase created successfully!')
        return redirect(url_for('purchases.purchases'))

    return render_template('purchases/form.html',
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

@purchases_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_purchase(id):
    purchase = Purchase.query.get_or_404(id)
    if request.method == 'POST':
        purchase.internal_id = request.form.get('internal_id')
        purchase.description = request.form['description']
        purchase.invoice_number = request.form.get('invoice_number')
        purchase.purchase_date = datetime.strptime(request.form['purchase_date'], '%Y-%m-%d').date()
        purchase.comments = request.form.get('comments')
        purchase.supplier_id = request.form.get('supplier_id') or None
        purchase.payment_method_id = request.form.get('payment_method_id') or None
        purchase.budget_id = request.form.get('budget_id') or None
        db.session.commit()
        flash('Purchase updated successfully!')
        return redirect(url_for('purchases.purchases'))

    return render_template('purchases/form.html',
                            purchase=purchase,
                            suppliers=Supplier.query.order_by(Supplier.name).all(),
                            users=User.query.order_by(User.name).all(),
                            payment_methods=PaymentMethod.query.order_by(PaymentMethod.name).all(),
                            tags=Tag.query.order_by(Tag.name).all(),
                            budgets=Budget.query.order_by(Budget.name).all())

@purchases_bp.route('/<int:id>/validate_cost', methods=['POST'])
@login_required
def validate_cost(id):
    purchase = Purchase.query.get_or_404(id)
    user_id = session.get('user_id')
    purchase.validated_cost = purchase.calculated_cost
    purchase.cost_validated_at = datetime.utcnow()
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
def unvalidate_cost(id):
    purchase = Purchase.query.get_or_404(id)
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