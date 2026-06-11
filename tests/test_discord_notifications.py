"""Tests for the Discord notification channel.

Discord delivery posts {"content": "..."} to an incoming-webhook URL stored on
the owning NotificationEvent, and treats 204 (Discord's success code) as success.
"""
from unittest.mock import patch, MagicMock
from src import notifications
from src.models import db
from src.models.notifications import NotificationEvent
from src.models.communications import ScheduledCommunication
from src.utils.timezone_helper import today


def _make_comm(target_type='subscription', target_id=1):
    comm = ScheduledCommunication(
        status='pending',
        scheduled_date=today(),
        target_type=target_type,
        target_id=target_id,
        recipient_email='owner@test.com',
        recipient_name='Owner',
        channel='discord',
    )
    db.session.add(comm)
    db.session.commit()
    return comm


def test_format_discord_message_bolds_subject_and_strips_html():
    out = notifications._format_discord_message('Renewal due', '<p>Hello <b>world</b></p>')
    assert out.startswith('**Renewal due**')
    assert '<p>' not in out and '<b>' not in out
    assert 'world' in out


def test_format_discord_message_caps_at_2000_chars():
    out = notifications._format_discord_message('S', '<p>' + ('x' * 5000) + '</p>')
    assert len(out) <= 2000
    assert out.endswith('...')


def test_discord_dispatch_success_on_204(app, init_database):
    with app.app_context():
        event = NotificationEvent(
            event_code='SUBSCRIPTION_RENEWAL',
            name='Subscription Renewal',
            channels=['discord'],
            discord_webhook_url='https://discord.com/api/webhooks/123/abc',
        )
        db.session.add(event)
        db.session.commit()
        comm = _make_comm()

        resp = MagicMock(status_code=204)
        with patch('src.notifications.requests.post', return_value=resp) as mock_post:
            ok = notifications._send_discord_notification(app, comm, 'Subj', '<p>body</p>')

        assert ok is True
        url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
        assert url == 'https://discord.com/api/webhooks/123/abc'
        assert kwargs['json']['content'].startswith('**Subj**')


def test_discord_dispatch_missing_url_fails(app, init_database):
    with app.app_context():
        event = NotificationEvent(
            event_code='SUBSCRIPTION_RENEWAL',
            name='Subscription Renewal',
            channels=['discord'],
            discord_webhook_url=None,
        )
        db.session.add(event)
        db.session.commit()
        comm = _make_comm()

        ok = notifications._send_discord_notification(app, comm, 'Subj', '<p>body</p>')
        assert ok is False
        assert 'No Discord webhook URL' in comm.error_message


def test_discord_dispatch_non_2xx_fails(app, init_database):
    with app.app_context():
        event = NotificationEvent(
            event_code='SUBSCRIPTION_RENEWAL',
            name='Subscription Renewal',
            channels=['discord'],
            discord_webhook_url='https://discord.com/api/webhooks/123/abc',
        )
        db.session.add(event)
        db.session.commit()
        comm = _make_comm()

        resp = MagicMock(status_code=404)
        with patch('src.notifications.requests.post', return_value=resp):
            ok = notifications._send_discord_notification(app, comm, 'Subj', '<p>body</p>')

        assert ok is False
        assert '404' in comm.error_message


def test_update_event_persists_discord_channel(auth_client, app):
    with app.app_context():
        event = NotificationEvent(event_code='LICENSE_EXPIRING', name='License Expiring')
        db.session.add(event)
        db.session.commit()
        event_id = event.id

    auth_client.post(f'/admin/notifications/{event_id}/update', data={
        'channel_discord': 'on',
        'discord_webhook_url': 'https://discord.com/api/webhooks/9/z',
    }, follow_redirects=True)

    with app.app_context():
        refreshed = db.session.get(NotificationEvent, event_id)
        assert 'discord' in refreshed.channels
        assert refreshed.discord_webhook_url == 'https://discord.com/api/webhooks/9/z'
