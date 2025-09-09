import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

# Import the models needed for the notification logic
from .models import Service, NotificationSetting

# --- Notification Functions ---

def send_email(app, subject, body, to_emails):
    """Send email notification using app config."""
    # Check for both a recipient and an email username in config
    if not to_emails or not app.config.get('EMAIL_USERNAME'):
        return False
    
    try:
        msg = MIMEMultipart()
        msg['From'] = app.config['EMAIL_USERNAME']
        msg['To'] = ', '.join(to_emails)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(app.config['SMTP_SERVER'], app.config['SMTP_PORT'])
        server.starttls()
        server.login(app.config['EMAIL_USERNAME'], app.config['EMAIL_PASSWORD'])
        server.send_message(msg)
        server.quit()
        app.logger.info(f"Sent renewal email to {to_emails}")
        return True
    except Exception as e:
        app.logger.error(f"Failed to send email: {e}")
        return False

def send_webhook(app, url, data):
    """Send webhook notification to a specific URL."""
    if not url:
        return False
    
    try:
        response = requests.post(url, json=data, timeout=10)
        app.logger.info(f"Sent webhook to {url}, status code: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        app.logger.error(f"Failed to send webhook: {e}")
        return False

def check_upcoming_renewals(app):
    """
    Checks for services that need renewal notifications based on user settings
    and sends alerts via email and/or webhooks.
    """
    with app.app_context():
        # Step 1: Fetch Notification Settings from the database
        settings = NotificationSetting.query.first()
        if not settings or (not settings.email_enabled and not settings.webhook_enabled):
            app.logger.info("Notifications are disabled. Skipping check.")
            return

        # Step 2: Determine which days require notifications
        try:
            notify_days = {int(day) for day in settings.notify_days_before.split(',') if day}
        except (ValueError, TypeError):
            app.logger.error("Invalid 'notify_days_before' format. Skipping check.")
            return
            
        if not notify_days:
            return # No notification days configured

        # Step 3: Find services that match the notification criteria
        today = datetime.now().date()
        services_to_notify = []
        all_services = Service.query.all()

        for service in all_services:
            days_until = (service.next_renewal_date - today).days
            # Check if the service is due on one of the configured notification days
            if days_until in notify_days:
                services_to_notify.append(service)

        # Step 4: If there are services to notify about, build and send the alerts
        if services_to_notify:
            html_content = "<h2>Upcoming Service Renewals</h2><ul>"
            webhook_data = {
                "text": "Upcoming Service Renewals",
                "renewals": []
            }
            
            for service in services_to_notify:
                days_until = (service.next_renewal_date - today).days
                html_content += f"<li><strong>{service.name}</strong> ({service.service_type}) - Renews in {days_until} days - €{service.cost_eur:.2f}</li>"
                webhook_data["renewals"].append({
                    "name": service.name,
                    "type": service.service_type,
                    "renewal_date": service.next_renewal_date.isoformat(),
                    "days_until": days_until,
                    "cost_eur": service.cost_eur
                })
            
            html_content += "</ul>"
            
            # Send email if enabled and a recipient is set
            if settings.email_enabled and settings.email_recipient:
                send_email(
                    app,
                    "Service Renewal Reminder", 
                    html_content,
                    [settings.email_recipient]
                )
            
            # Send webhook if enabled and a URL is set
            if settings.webhook_enabled and settings.webhook_url:
                send_webhook(app, settings.webhook_url, webhook_data)
        else:
            app.logger.info("No services require notification today.")