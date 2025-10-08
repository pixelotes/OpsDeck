from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, Purchase, Supplier, User, PaymentMethod, Tag, Budget
from .main import login_required

purchases_bp = Blueprint('purchases', __name__)

@purchases_bp.route('/')
@login_required
def purchases():
    purchases = Purchase.query.all()
    return render_template('purchases/list.html', purchases=purchases)

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
            cost=float(request.form['cost']),
            currency=request.form['currency'],
            comments=request.form.get('comments'),
            supplier_id=request.form.get('supplier_id'),
            payment_method_id=request.form.get('payment_method_id'),
            budget_id=request.form.get('budget_id')
        )

        for user_id in request.form.getlist('user_ids'):
            user = User.query.get(user_id)
            if user:
                purchase.users.append(user)

        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                purchase.tags.append(tag)

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
        purchase.cost = float(request.form['cost'])
        purchase.currency = request.form['currency']
        purchase.comments = request.form.get('comments')
        purchase.supplier_id = request.form.get('supplier_id')
        purchase.payment_method_id = request.form.get('payment_method_id')
        purchase.budget_id = request.form.get('budget_id')

        purchase.users.clear()
        for user_id in request.form.getlist('user_ids'):
            user = User.query.get(user_id)
            if user:
                purchase.users.append(user)

        purchase.tags.clear()
        for tag_id in request.form.getlist('tag_ids'):
            tag = Tag.query.get(tag_id)
            if tag:
                purchase.tags.append(tag)

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