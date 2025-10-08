from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Budget
from .main import login_required

budgets_bp = Blueprint('budgets', __name__)

@budgets_bp.route('/')
@login_required
def budgets():
    budgets = Budget.query.all()
    return render_template('budgets/list.html', budgets=budgets)

@budgets_bp.route('/<int:id>')
@login_required
def budget_detail(id):
    budget = Budget.query.get_or_404(id)
    return render_template('budgets/detail.html', budget=budget)

@budgets_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_budget():
    if request.method == 'POST':
        budget = Budget(
            name=request.form['name'],
            category=request.form.get('category'),
            amount=float(request.form['amount']),
            currency=request.form['currency'],
            period=request.form['period']
        )
        db.session.add(budget)
        db.session.commit()
        flash('Budget created successfully!')
        return redirect(url_for('budgets.budgets'))

    return render_template('budgets/form.html')

@budgets_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_budget(id):
    budget = Budget.query.get_or_404(id)

    if request.method == 'POST':
        budget.name = request.form['name']
        budget.category = request.form.get('category')
        budget.amount = float(request.form['amount'])
        budget.currency = request.form['currency']
        budget.period = request.form['period']
        db.session.commit()
        flash('Budget updated successfully!')
        return redirect(url_for('budgets.budgets'))

    return render_template('budgets/form.html', budget=budget)