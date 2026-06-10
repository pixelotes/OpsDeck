from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, Budget
from ..services.permissions_service import requires_permission, has_write_permission
from .main import login_required

budgets_bp = Blueprint('budgets', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'finance'
BUDGETS = 'budgets.budgets'
BUDGETS_FORM_HTML = 'budgets/form.html'

@budgets_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def budgets():
    budgets = Budget.query.all()
    return render_template('budgets/list.html', budgets=budgets)

@budgets_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def budget_detail(id):
    budget = db.get_or_404(Budget, id)
    return render_template('budgets/detail.html', budget=budget)

@budgets_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_budget():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for(BUDGETS))

        # Validate amount
        try:
            amount = float(request.form['amount'])
            if amount <= 0:
                flash('Budget amount must be greater than 0.', 'danger')
                return render_template(BUDGETS_FORM_HTML)
        except (ValueError, KeyError):
            flash('Invalid amount value.', 'danger')
            return render_template(BUDGETS_FORM_HTML)

        budget = Budget(
            name=request.form['name'],
            category=request.form.get('category'),
            amount=amount,
            currency=request.form.get('currency', 'EUR'), # Use .get() and add default
            period=request.form.get('period', 'One-time'), # Use .get() and add default
            valid_from=datetime.strptime(request.form['valid_from'], '%Y-%m-%d').date(),
            valid_until=datetime.strptime(request.form['valid_until'], '%Y-%m-%d').date()
        )
        db.session.add(budget)
        db.session.commit()
        flash('Budget created successfully!', 'success')
        return redirect(url_for(BUDGETS))

    return render_template(BUDGETS_FORM_HTML)

@budgets_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_budget(id):
    budget = db.get_or_404(Budget, id)

    if request.method == 'POST':
        if not has_write_permission(MODULE):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('budgets.budget_detail', id=id))

        # Validate amount
        try:
            amount = float(request.form['amount'])
            if amount <= 0:
                flash('Budget amount must be greater than 0.', 'danger')
                return render_template(BUDGETS_FORM_HTML, budget=budget)
        except (ValueError, KeyError):
            flash('Invalid amount value.', 'danger')
            return render_template(BUDGETS_FORM_HTML, budget=budget)

        budget.name = request.form['name']
        budget.category = request.form.get('category')
        budget.amount = amount
        budget.currency = request.form['currency']
        budget.period = request.form['period']
        budget.valid_from = datetime.strptime(request.form['valid_from'], '%Y-%m-%d').date()
        budget.valid_until = datetime.strptime(request.form['valid_until'], '%Y-%m-%d').date()
        db.session.commit()
        flash('Budget updated successfully!', 'success')
        return redirect(url_for(BUDGETS))

    return render_template(BUDGETS_FORM_HTML, budget=budget)