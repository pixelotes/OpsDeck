from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Risk
from .main import login_required
from .admin import admin_required

risk_bp = Blueprint('risk', __name__)

@risk_bp.route('/')
@login_required
def list_risks():
    risks = Risk.query.order_by(Risk.created_at.desc()).all()
    return render_template('risk/list.html', risks=risks)

@risk_bp.route('/<int:id>')
@login_required
def detail(id):
    risk = Risk.query.get_or_404(id)
    return render_template('risk/detail.html', risk=risk)

@risk_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_risk():
    if request.method == 'POST':
        risk = Risk(
            risk_description=request.form['risk_description'],
            risk_owner=request.form.get('risk_owner'),
            status=request.form.get('status'),
            likelihood=request.form.get('likelihood'),
            impact=request.form.get('impact'),
            mitigation_plan=request.form.get('mitigation_plan'),
            iso_27001_control=request.form.get('iso_27001_control'),
            link=request.form.get('link')
        )
        db.session.add(risk)
        db.session.commit()
        flash('Risk has been successfully logged.', 'success')
        return redirect(url_for('risk.list_risks'))

    return render_template('risk/form.html')

@risk_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_risk(id):
    risk = Risk.query.get_or_404(id)
    if request.method == 'POST':
        risk.risk_description = request.form['risk_description']
        risk.risk_owner = request.form.get('risk_owner')
        risk.status = request.form.get('status')
        risk.likelihood = request.form.get('likelihood')
        risk.impact = request.form.get('impact')
        risk.mitigation_plan = request.form.get('mitigation_plan')
        risk.iso_27001_control = request.form.get('iso_27001_control')
        risk.link = request.form.get('link')
        db.session.commit()
        flash('Risk has been updated.', 'success')
        return redirect(url_for('risk.list_risks'))

    return render_template('risk/form.html', risk=risk)