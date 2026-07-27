"""
Email Notification Service Module
Handles sending email notifications for course assignments and reminders

Transport design
----------------
Sending used to open a brand-new SMTP connection per message — connect, STARTTLS,
AUTH, send, disconnect. A 197-recipient assignment therefore meant 197 logins to
smtp.office365.com fired 8-wide, which is several times over Office 365's SMTP AUTH
client-submission limits (3 concurrent connections, 30 messages/minute). The server
answered with transient 4.x.x refusals and, because nothing retried, roughly a fifth
of the batch was silently dropped.

Three things fix that, and they only work together:

* ``SmtpSession`` keeps ONE authenticated connection alive across many messages, so
  a batch costs one login instead of N.
* ``_RateLimiter`` paces every send globally (default 30/min, ``SMTP_RATE_PER_MIN``).
* ``send_email`` retries with exponential backoff — but only what is worth retrying.
  A 4xx response, a dropped connection or a timeout is transient. A 5xx rejection
  (unknown recipient, refused message) and a syntactically invalid address are
  permanent: they are logged with the address and the server's exact wording, and
  never retried.

Every outcome — sent, retried, permanently rejected, given up on — is logged with
the recipient address, so `logs/app.log` is a complete delivery record.
"""

import logging
import os
import random
import re
import smtplib
import socket
import ssl
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# No basicConfig here: this is a library module, and configuring the root logger at
# import time would hijack the host app's handlers. app.py owns logging config; the
# __main__ block below sets up its own when this file is run directly.
logger = logging.getLogger(__name__)

# SMTP Configuration
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.office365.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
SENDER_ADDRESS = SMTP_USERNAME
SMTP_TIMEOUT = int(os.environ.get('SMTP_TIMEOUT', '30'))

# Retry policy. Backoff is chosen per failure kind, because the two throttles the
# server applies have very different recovery times:
#
#   concurrency (432 4.3.2) — a connection frees up within seconds, so the ordinary
#       exponential backoff (2s, 4s, 8s, 16s) is the right shape.
#   rate limit  (4.4.2 etc.) — assessed over a ROLLING MINUTE. Exponential backoff is
#       useless here: 2+4+8+16s of patience expires long before the window does, and
#       every attempt is spent inside the throttle. These wait SMTP_RATE_COOLDOWN
#       instead, and pause every other sender with them (see _RateLimiter.pause).
SMTP_MAX_ATTEMPTS = max(1, int(os.environ.get('SMTP_MAX_ATTEMPTS', '5')))
SMTP_BACKOFF_BASE = float(os.environ.get('SMTP_BACKOFF_BASE', '2.0'))
SMTP_BACKOFF_CAP = float(os.environ.get('SMTP_BACKOFF_CAP', '60'))
# Long enough to outlast a rolling-minute window, with margin for clock skew.
SMTP_RATE_COOLDOWN = float(os.environ.get('SMTP_RATE_COOLDOWN', '75'))
# Explicit messages/minute throttle. DISABLED by default (0), deliberately.
#
# Microsoft publishes 30 messages/minute for SMTP AUTH client submission, but the
# production logs show this tenant sustaining 660/minute (peak 13/second) with zero
# rate-limit responses — every single refusal was 432 4.3.2 concurrency, never a
# 4.4.x/4.7.x throttle. Throttling to 30/min would be 22x slower than the rate the
# server demonstrably accepts, in exchange for a limit there is no evidence it
# enforces.
#
# Pacing is instead a consequence of SMTP_MAX_CONNECTIONS: three serial SMTP
# conversations physically cannot exceed a few messages per second, which is the
# throughput profile that already worked. Set this to a positive number only if the
# logs start showing genuine rate refusals (4.4.x / 4.7.x).
SMTP_RATE_PER_MIN = int(os.environ.get('SMTP_RATE_PER_MIN', '0'))

# NOTE on concurrent connections. The limit production actually hit was
#   432 4.3.2 Concurrent connections limit exceeded (aka.ms/concurrent_sending)
# so the number of connections open at once is the critical quantity. It is bounded
# structurally rather than here: one session per worker thread, and app.py runs every
# dispatch through a single serialised job runner with EMAIL_WORKERS threads. A
# semaphore in this module would look tempting but starves — a session holds its
# connection for a whole batch, so two overlapping batches would deadlock on it.

# Deliberately permissive — this only catches addresses that can never be delivered
# (empty, no @, spaces, no dot in the domain). Anything plausible goes to the server,
# which is the real authority on whether a mailbox exists.
_ADDR_RE = re.compile(
    r"^[^@\s,;:<>\"\\]+@[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")


class SmtpConfigError(RuntimeError):
    """Credentials or server config are wrong, not this one message.

    Every remaining message in the batch would fail identically, and hammering AUTH
    is how an account gets locked out — so callers should abort the batch instead of
    retrying. Raised only for a 5xx AUTH rejection; a 4xx one is a temporary
    throttle and stays retryable.
    """


# Failure categories. These drive three decisions: how long to back off, whether to
# retry at all, and whether a later re-send is worth attempting.
#
#   'concurrency' too many simultaneous connections -> short backoff, retry
#   'rate'        messages/minute throttle          -> long cooldown, retry
#   'quota'       daily/mailbox quota exhausted     -> no retry now, re-send later
#   'address'     malformed or unknown mailbox      -> no retry, address must be fixed
#   'auth'        credentials rejected              -> abort the batch
#   'transient'   anything else recoverable         -> short backoff, retry
CAT_CONCURRENCY = 'concurrency'
CAT_RATE = 'rate'
CAT_QUOTA = 'quota'
CAT_ADDRESS = 'address'
CAT_AUTH = 'auth'
CAT_TRANSIENT = 'transient'

# Matched against the server's own words, lowercased. Concurrency is tested FIRST:
# "Concurrent connections limit exceeded" also contains "limit exceeded", which would
# otherwise be read as a rate limit and earn a needless 75-second cooldown.
_CONCURRENCY_MARKERS = ('concurrent connection', 'concurrent sending',
                        'too many concurrent')
_RATE_MARKERS = ('4.4.2', 'submission rate', 'message rate', 'rate limit',
                 'rate exceeded', 'throttl', 'too many messages',
                 'sending limit', 'try again later', 'server busy',
                 # Exchange's wording for the messages/minute limit.
                 'storedrv.clientsubmit', 'thread limit')
_QUOTA_MARKERS = ('5.7.232', 'daily limit', 'over quota', 'quota exceeded',
                  'mailbox is full', 'mailbox full', 'insufficient system storage')
_ADDRESS_MARKERS = ('recipientnotfound', 'user unknown', 'unknown recipient',
                    'no such user', 'does not exist', 'invalid recipient',
                    'address rejected', '5.1.1', '5.1.10')


def _categorize(code, reason):
    """Classify a server response by what it actually means for delivery."""
    text = (reason or '').lower()
    if any(m in text for m in _CONCURRENCY_MARKERS):
        return CAT_CONCURRENCY
    if any(m in text for m in _QUOTA_MARKERS):
        return CAT_QUOTA
    if any(m in text for m in _RATE_MARKERS):
        return CAT_RATE
    if any(m in text for m in _ADDRESS_MARKERS):
        return CAT_ADDRESS
    try:
        if 500 <= int(code) < 600:
            return CAT_ADDRESS   # an unexplained hard rejection is address-shaped
    except (TypeError, ValueError):
        pass
    return CAT_TRANSIENT


class SendResult:
    """Outcome of one send attempt chain.

    Falsy when the send failed, so existing call sites that do ``if send_email(...)``
    or ``return send_email(...)`` keep working unchanged, while the email-job runner
    can read ``.reason`` to report exactly who was missed and why.

    ``permanent`` means "do not retry inside this job". ``resendable`` is the
    different question of whether a later re-send could succeed — a quota failure is
    permanent for today but worth retrying tomorrow, whereas an unknown mailbox is
    not worth retrying until someone corrects the address.
    """

    __slots__ = ('ok', 'address', 'reason', 'code', 'attempts', 'permanent', 'category')

    def __init__(self, ok, address, reason='', code=None, attempts=1, permanent=False,
                 category=CAT_TRANSIENT):
        self.ok = bool(ok)
        self.address = address
        self.reason = reason
        self.code = code
        self.attempts = attempts
        self.permanent = permanent
        self.category = category

    def __bool__(self):
        return self.ok

    @property
    def resendable(self):
        """Is a later re-send worth attempting?

        Only a bad address is not: it needs correcting per recipient first. Rate,
        concurrency, quota and auth failures are all conditions that clear on their
        own or with one fix, after which re-sending the same address should work.
        """
        return self.category != CAT_ADDRESS

    def as_dict(self):
        return {'email': self.address, 'reason': self.reason, 'code': self.code,
                'attempts': self.attempts, 'permanent': self.permanent,
                'category': self.category, 'resendable': self.resendable}

    def __repr__(self):
        state = 'ok' if self.ok else ('permanent' if self.permanent else 'transient')
        return f'<SendResult {self.address} {state}/{self.category} {self.reason!r}>'


class _RateLimiter:
    """Global send gate shared by every worker thread. Two mechanisms:

    * a steady-state pace of ``per_minute`` messages (0 = unpaced, the default —
      the connection ceiling already bounds throughput);
    * an ADAPTIVE COOLDOWN. When the server says the rate has been exceeded, the
      condition is global, not specific to that one message. Letting each worker
      discover it independently would burn every message's retry budget against the
      same throttle. ``pause()`` stops all senders at once, so a rate limit costs one
      shared wait instead of N separate failures.
    """

    def __init__(self, per_minute):
        self._interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0
        self._cooldown_until = 0.0

    def acquire(self):
        # Honour an active cooldown first. Re-checked in slices because another
        # worker may extend it while this one is waiting.
        while True:
            with self._lock:
                remaining = self._cooldown_until - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(remaining, 5.0))

        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            time.sleep(wait)

    def pause(self, seconds):
        """Hold every sender for ``seconds``. Returns True if this call set a new,
        later cooldown (so only the first worker to notice logs it)."""
        with self._lock:
            target = time.monotonic() + seconds
            if target > self._cooldown_until:
                self._cooldown_until = target
                return True
            return False

    @property
    def cooling_down(self):
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())


_rate_limiter = _RateLimiter(SMTP_RATE_PER_MIN)


def _decode(value):
    """SMTP error text arrives as bytes; make it readable for logs."""
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace').strip()
    return str(value or '').strip()


def valid_address(address):
    """True if the address is worth handing to the SMTP server at all."""
    return bool(address) and len(address) <= 320 and _ADDR_RE.match(address) is not None


def _classify(exc):
    """Map an exception to (permanent, code, reason, category).

    ``permanent`` means retrying inside this job cannot help — a bad or unknown
    recipient, a refused body, an exhausted daily quota. Everything else is retried,
    with the category deciding how patiently (see SMTP_RATE_COOLDOWN).
    """
    def done(code, reason, force_permanent=None):
        category = _categorize(code, reason)
        if force_permanent is not None:
            permanent = force_permanent
        elif category in (CAT_CONCURRENCY, CAT_RATE, CAT_TRANSIENT):
            permanent = False
        elif category == CAT_QUOTA:
            # A daily/mailbox quota will not clear inside a retry window, but it is
            # not the address's fault either — re-send once it resets.
            permanent = True
        else:
            permanent = True
        return permanent, code, reason, category

    # Not a subclass of SMTPResponseException, so it has to come first.
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        recipients = getattr(exc, 'recipients', {}) or {}
        if recipients:
            code, msg = next(iter(recipients.values()))
            code, msg = int(code), _decode(msg)
            # A 4xx recipient refusal is transient whatever the wording suggests.
            return done(code, msg, force_permanent=False if code < 500 else None)
        return done(None, 'Recipient refused by server', force_permanent=True)

    # A failed connection reports the server's greeting code, but the condition is
    # about the server's availability, not this message — always retryable.
    if isinstance(exc, smtplib.SMTPConnectError):
        code = getattr(exc, 'smtp_code', None)
        return done(code, _decode(getattr(exc, 'smtp_error', exc)), force_permanent=False)

    if isinstance(exc, smtplib.SMTPResponseException):
        code = getattr(exc, 'smtp_code', None)
        reason = _decode(getattr(exc, 'smtp_error', exc))
        try:
            code = int(code)
        except (TypeError, ValueError):
            return done(None, reason, force_permanent=False)
        # 4xx is transient by definition; 5xx falls to the category rules.
        return done(code, reason, force_permanent=False if code < 500 else None)

    if isinstance(exc, smtplib.SMTPServerDisconnected):
        reason = f'Server disconnected: {exc}' if str(exc) else 'Server disconnected'
        return False, None, reason, CAT_TRANSIENT

    if isinstance(exc, (socket.timeout, TimeoutError)):
        return False, None, 'Timed out talking to SMTP server', CAT_TRANSIENT

    if isinstance(exc, (socket.gaierror, ConnectionError, OSError, ssl.SSLError)):
        return False, None, f'{type(exc).__name__}: {exc}', CAT_TRANSIENT

    return False, None, f'{type(exc).__name__}: {exc}', CAT_TRANSIENT


class SmtpSession:
    """One authenticated SMTP connection, reused across many messages.

    Not thread-safe on purpose — an SMTP connection is a single command stream, so
    give each worker thread its own session (see app._run_email_job). The connection
    is opened lazily on first send and re-opened transparently if the server drops
    it, which O365 does routinely on idle or throttled connections.
    """

    def __init__(self, server=None, port=None, username=None, password=None, timeout=None):
        self.server = server or SMTP_SERVER
        self.port = port or SMTP_PORT
        self.username = username if username is not None else SMTP_USERNAME
        self.password = password if password is not None else SMTP_PASSWORD
        self.timeout = timeout or SMTP_TIMEOUT
        self.sent_count = 0
        self.connect_count = 0
        self._conn = None

    def _ensure(self):
        if self._conn is not None:
            try:
                self._conn.noop()
                return self._conn
            except Exception as e:
                logger.info(f'SMTP connection went stale ({e}); reconnecting')
                self.invalidate()

        conn = smtplib.SMTP(self.server, self.port, timeout=self.timeout)
        try:
            conn.ehlo()
            conn.starttls(context=ssl.create_default_context())
            conn.ehlo()
            conn.login(self.username, self.password)
        except smtplib.SMTPAuthenticationError as e:
            code = getattr(e, 'smtp_code', None)
            reason = _decode(getattr(e, 'smtp_error', e))
            self._close_quietly(conn)
            if code and 400 <= int(code) < 500:
                # e.g. 454 4.7.0 "Too many login attempts", or the 432 4.3.2
                # concurrency refusal — throttles, so let the caller back off and
                # retry rather than abandoning the batch.
                logger.warning(f'SMTP auth throttled ({code}): {reason}')
                raise
            logger.error(f'SMTP authentication rejected for {self.username} ({code}): {reason}')
            raise SmtpConfigError(f'SMTP authentication rejected ({code}): {reason}') from e
        except Exception:
            self._close_quietly(conn)
            raise

        self._conn = conn
        self.connect_count += 1
        logger.info(f'SMTP connection opened to {self.server}:{self.port} as {self.username} '
                    f'(connection #{self.connect_count} for this session)')
        return conn

    def send(self, msg, to_address):
        conn = self._ensure()
        conn.send_message(msg, to_addrs=[to_address])
        self.sent_count += 1

    @staticmethod
    def _close_quietly(conn):
        try:
            conn.close()
        except Exception:
            pass

    def invalidate(self):
        """Drop the connection without a polite QUIT — used when it is already broken."""
        if self._conn is not None:
            self._close_quietly(self._conn)
            self._conn = None

    def close(self):
        if self._conn is None:
            return
        try:
            self._conn.quit()
            self._conn = None
        except Exception:
            self.invalidate()
        logger.info(f'SMTP session closed after {self.sent_count} message(s)')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _build_message(to_address, subject, body_html, body_text=None):
    msg = MIMEMultipart('alternative')
    msg['From'] = SENDER_ADDRESS
    msg['To'] = to_address
    msg['Subject'] = subject
    # Date and Message-ID are absent from bare MIMEMultipart and their absence is a
    # spam-filter signal; several receivers score mail without them.
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid()
    if body_text:
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))
    return msg


def send_email(to_address, subject, body_html, body_text=None, session=None):
    """
    Send an email notification, retrying transient SMTP failures.

    Args:
        to_address (str): Recipient email address
        subject (str): Email subject
        body_html (str): HTML body content
        body_text (str, optional): Plain text body content
        session (SmtpSession, optional): Connection to reuse. Pass one when sending a
            batch — otherwise a throwaway connection is opened and closed per message,
            which is what the per-message-connection design used to do.

    Returns:
        SendResult: falsy on failure, carrying .reason / .code / .attempts. Callers
        that treat the return value as a bool keep working.

    Raises:
        SmtpConfigError: credentials were rejected outright. Not a per-message
            failure — the caller should abort the whole batch.
    """
    address = (to_address or '').strip()

    # Rejected before any network call: no server round-trip can fix a malformed
    # address, and it must still be reported rather than swallowed.
    if not valid_address(address):
        logger.error(f'INVALID ADDRESS — not sending: {address!r} (subject: {subject!r})')
        return SendResult(False, address, 'Invalid email address', attempts=0,
                          permanent=True, category=CAT_ADDRESS)

    msg = _build_message(address, subject, body_html, body_text)
    own_session = session is None
    sess = session or SmtpSession()
    result = None

    try:
        for attempt in range(1, SMTP_MAX_ATTEMPTS + 1):
            _rate_limiter.acquire()
            try:
                sess.send(msg, address)
                if attempt > 1:
                    logger.info(f'Email sent successfully to {address} on attempt '
                                f'{attempt}/{SMTP_MAX_ATTEMPTS} (subject: {subject!r})')
                else:
                    logger.info(f'Email sent successfully to {address}')
                return SendResult(True, address, attempts=attempt)
            except SmtpConfigError:
                raise
            except Exception as e:
                permanent, code, reason, category = _classify(e)
                result = SendResult(False, address, reason, code, attempt, permanent,
                                    category)

                if permanent:
                    logger.error(f'PERMANENT delivery failure for {address} '
                                 f'[{category}/{code or "-"}]: {reason} — not retrying')
                    return result

                # Transient: the connection may be half-dead, so force a fresh one.
                sess.invalidate()

                if attempt >= SMTP_MAX_ATTEMPTS:
                    logger.error(f'GAVE UP on {address} after {attempt} attempt(s) '
                                 f'[{category}/{code or "-"}]: {reason}')
                    return result

                if category == CAT_RATE:
                    # The throttle is assessed over a rolling minute and applies to
                    # every sender, so wait it out properly and take the other
                    # workers with us instead of each one rediscovering it.
                    delay = SMTP_RATE_COOLDOWN
                    if _rate_limiter.pause(delay):
                        logger.warning(
                            f'RATE LIMIT reported by server [{code or "-"}]: {reason} '
                            f'— pausing all senders for {delay:.0f}s')
                else:
                    delay = min(SMTP_BACKOFF_BASE ** attempt, SMTP_BACKOFF_CAP)
                    delay += random.uniform(0, delay * 0.25)  # jitter: avoid lockstep

                logger.warning(f'Transient failure for {address} on attempt '
                               f'{attempt}/{SMTP_MAX_ATTEMPTS} [{category}/{code or "-"}]: '
                               f'{reason} — retrying in {delay:.1f}s')
                time.sleep(delay)

        return result
    finally:
        if own_session:
            sess.close()


# ── Email templates ─────────────────────────────────────────────────────────
# Colour rule for every banner below: white heading text must stay readable at BOTH
# ends of the gradient, because a reader may see either the gradient or the flat
# fallback. Every pair here clears 4.8:1 against white. Do not swap in a lighter
# brand colour without re-checking — the amber #f59e0b this template used to sit on
# gave 2.15:1, which is why the reminder's title was unreadable.

def _email_header(icon, title, grad_from, grad_to, badge=None):
    """Build the coloured banner at the top of a notification email.

    A table with a ``bgcolor`` attribute and fully inlined colours, rather than a
    styled ``<div class="header">``, because of two things mail clients do:

    * Outlook's Word rendering engine ignores ``linear-gradient`` outright. A banner
      whose colour lives only in a gradient renders with **no background at all**, so
      the white title lands on white and disappears.
    * Several clients (Outlook.com, some Gmail paths) strip ``<style>`` blocks, so a
      title coloured by a CSS class loses its colour too.

    ``bgcolor`` plus an inline ``background-color`` is honoured essentially
    everywhere; the gradient rides on top purely as an enhancement.
    """
    badge_html = ''
    if badge:
        # A solid white pill with dark text. The previous rgba(255,255,255,.3) badge
        # depended on alpha compositing, which Outlook does not do, and was low
        # contrast even where it worked.
        badge_html = (
            f'<div style="margin:8px 0 0;">'
            f'<span style="display:inline-block;background-color:#ffffff;color:{grad_to};'
            f'padding:4px 14px;border-radius:20px;font-size:12px;font-weight:700;'
            f'font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;">{badge}</span>'
            f'</div>')

    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'border="0" style="border-collapse:collapse;">'
        f'<tr>'
        f'<td bgcolor="{grad_from}" align="center" '
        f'style="background-color:{grad_from};'
        f'background-image:linear-gradient(135deg,{grad_from} 0%,{grad_to} 100%);'
        f'padding:20px 15px;text-align:center;">'
        f'<div style="font-size:34px;line-height:1;margin:0 0 6px;">{icon}</div>'
        f'<h1 style="margin:0;font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;'
        f'font-size:22px;line-height:1.3;font-weight:600;color:#ffffff;">{title}</h1>'
        f'{badge_html}'
        f'</td>'
        f'</tr>'
        f'</table>')


def send_course_assignment_email(user_email, user_name, course_name, deadline, session=None):
    """
    Send course assignment notification to user with styled HTML template

    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the assigned course
        deadline (str): Course completion deadline (YYYY-MM-DD)
        session (SmtpSession, optional): connection to reuse across a batch

    Returns:
        SendResult: falsy if the email could not be delivered
    """
    subject = f"📚 New Course Assignment: {course_name}"

    # The title used to be a <span class="label">, and .label is #667eea — the same
    # colour as the banner's gradient start, so the heading was invisible against its
    # own background. It is now white on a dark violet that clears 6.3:1.
    header_html = _email_header('📚', 'New Course Assignment', '#5b46c9', '#764ba2')

    # Enhanced HTML email template optimized for both desktop and mobile
    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
        
        /* Base styles */
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        /* The banner is built by _email_header() with fully inlined colours — it
           must not depend on these rules surviving the mail client. */

        .content {{ 
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .greeting {{
            font-size: 15px;
            color: #333333;
            margin-bottom: 15px;
        }}
        
        .message-box {{
            background: #f0f4ff;
            border-left: 4px solid #667eea;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .details-table {{ 
            width: 100%; 
            margin: 20px 0;
            border-collapse: collapse;
            background: #ffffff;
        }}
        
        .details-table td {{ 
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        
        .details-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .label {{ 
            font-weight: 600; 
            color: #667eea;
            width: 40%;
        }}
        
        .value {{
            color: #333333;
            font-weight: 500;
        }}
        
        .cta-button {{ 
            display: inline-block;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #ffffff !important;
            padding: 12px 28px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            margin: 15px 0;
            text-align: center;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        /* Mobile responsive */
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
            .cta-button {{ padding: 10px 22px; font-size: 14px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        {header_html}

            <div class="message-box">
                <p style="margin: 0; font-size: 14px;">
                    <p style="font-weight:600">Dear {user_name},</p> <p>A new course has been assigned to you as part of our Safety & Health Excellence program. Kindly ignore if already completed.</p>
                </p>
            </div>

            <table class="details-table">
                <tr>
                    <td class="label">📖 Course Name:</td>
                    <td class="value">{course_name}</td>
                </tr>
                <tr>
                    <td class="label">📅 Deadline:</td>
                    <td class="value">{deadline}</td>
                </tr>
            </table>

            <p style="margin: 15px 0; font-size: 14px; color: #495057;">
                Please log in to the Tata Tomorrow University portal to access your course materials and begin your learning journey.
            </p>

            <center>
                <a href="https://www.tmtctata.com/" class="cta-button"
                   style="display:inline-block;background:#667eea;color:#ffffff;padding:12px 28px;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px;margin:15px 0;">
                    Access Course Portal
                </a>
            </center>

        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    # Plain text fallback template
    body_text = f"""Dear {user_name},

A new course has been assigned to you as part of our Safety & Health Excellence program. Kindly ignore if already completed.

Course Details:
📖 Course Name: {course_name}
📅 Deadline: {deadline}

Please log in to the Tata Tomorrow University portal to access your course materials:
https://www.tmtctata.com/

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""

    return send_email(user_email, subject, body_html, body_text, session=session)


def send_deadline_reminder_email(user_email, user_name, course_name, deadline, days_remaining,
                                 session=None):
    """
    Send deadline reminder notification to user

    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the course
        deadline (str): Course completion deadline
        days_remaining (int): Days remaining until deadline
        session (SmtpSession, optional): connection to reuse across a batch

    Returns:
        SendResult: falsy if the email could not be delivered
    """
    subject = f"⏰ REMINDER: Course Deadline - {course_name}"

    urgent = days_remaining <= 3
    urgency_text = "URGENT" if urgent else "Important"
    # Two separate colours, because the same hue cannot serve both jobs. The old
    # template reused one value for the header background AND for text on white; the
    # non-urgent amber (#f59e0b) gave white-on-amber at 2.15:1 in the header — the
    # title was effectively invisible — and amber-on-white at 2.15:1 in the body.
    # header_* are dark enough for white text (>=4.8:1); accent_color is dark enough
    # to read on white (>=5:1). See the contrast note above _EMAIL_HEADER.
    header_from = "#dc2626" if urgent else "#b45309"
    header_to = "#991b1b" if urgent else "#92400e"
    accent_color = "#b91c1c" if urgent else "#b45309"
    header_html = _email_header('⏰', 'Course Deadline Reminder',
                                header_from, header_to, badge=urgency_text)

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        /* The banner is built by _email_header() with fully inlined colours — it
           must not depend on these rules surviving the mail client. */

        .content {{
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .alert-box {{
            background: #fff3cd;
            border-left: 4px solid {accent_color};
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .details-table {{ 
            width: 100%; 
            margin: 20px 0;
            border-collapse: collapse;
            background: #ffffff;
        }}
        
        .details-table td {{ 
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }}
        
        .details-table tr:last-child td {{
            border-bottom: none;
        }}
        
        .label {{
            font-weight: 600;
            color: {accent_color};
            width: 45%;
        }}
        
        .value {{
            color: #333333;
            font-weight: 500;
        }}
        
        .days-remaining {{
            color: {accent_color};
            font-weight: 700;
            font-size: 18px;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        {header_html}

        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>
            
            <div class="alert-box">
                <p style="margin: 0; font-size: 14px; font-weight: 600;">
                    ⚠️ Your course deadline is approaching!
                </p>
            </div>
            
            <table class="details-table">
                <tr>
                    <td class="label">📖 Course Name:</td>
                    <td class="value">{course_name}</td>
                </tr>
                <tr>
                    <td class="label">📅 Final Deadline:</td>
                    <td class="value">{deadline}</td>
                </tr>
                <tr>
                    <td class="label">⏳ Days Remaining:</td>
                    <td class="days-remaining">{days_remaining} days</td>
                </tr>
            </table>
            
            <p style="margin: 15px 0; font-size: 14px; color: #495057;">
                Please complete this course before the deadline to ensure your progress is recorded and compliance requirements are met.
            </p>

            <div style="text-align:center;margin:0 0 8px;">
                <a href="https://www.tmtctata.com/"
                   style="display:inline-block;background:{accent_color};color:#ffffff;padding:13px 32px;text-decoration:none;border-radius:6px;font-weight:600;font-size:15px;letter-spacing:0.3px;">
                    Access Course Portal
                </a>
            </div>
        </div>
        
        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated reminder. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    body_text = f"""⏰ REMINDER: Course Deadline Approaching

Dear {user_name},

This is a reminder that your course deadline is approaching!

Course Details:
📖 Course Name: {course_name}
📅 Final Deadline: {deadline}
⏳ Days Remaining: {days_remaining} days

Please complete this course before the deadline to ensure your progress is recorded.

Access the Tata Tomorrow University portal here:
https://www.tmtctata.com/

Regards,
Safety & Health Excellence Support Team

---
This is an automated reminder."""

    return send_email(user_email, subject, body_html, body_text, session=session)


def send_course_removal_email(user_email, user_name, course_name, session=None):
    """
    Send notification when user is removed from a course assignment

    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the course
        session (SmtpSession, optional): connection to reuse across a batch

    Returns:
        SendResult: falsy if the email could not be delivered
    """
    subject = f"Course Assignment Removed: {course_name}"

    header_html = _email_header('ℹ️', 'Course Assignment Update', '#5b6472', '#4b5563')

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
        
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5; 
            color: #333333; 
            margin: 0; 
            padding: 0;
            background-color: #f4f4f4;
        }}
        
        .email-container {{ 
            max-width: 600px; 
            margin: 15px auto; 
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}
        
        /* The banner is built by _email_header() with fully inlined colours — it
           must not depend on these rules surviving the mail client. */

        .content {{ 
            padding: 20px 20px;
            background: #ffffff;
        }}
        
        .info-box {{ 
            background: #f3f4f6;
            border-left: 4px solid #6b7280;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}
        
        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}
        
        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}
        
        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}
        
        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        {header_html}

        
        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>
            
            <p style="font-size: 14px; color: #495057; margin: 12px 0;">
                This is to inform you that you have been removed from the following course assignment:
            </p>
            
            <div class="info-box">
                <p style="margin: 0; font-size: 14px;">
                    <strong>📖 Course:</strong> {course_name}
                </p>
            </div>
            
            <p style="font-size: 14px; color: #495057; margin: 15px 0;">
                You are no longer required to complete this course. If you believe this is an error, please contact your administrator.
            </p>
        </div>
        
        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety & Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    
    body_text = f"""Course Assignment Update

Dear {user_name},

This is to inform you that you have been removed from the following course assignment:

📖 Course: {course_name}

You are no longer required to complete this course. If you believe this is an error, please contact your administrator.

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""

    return send_email(user_email, subject, body_html, body_text, session=session)


def send_course_completion_email(user_email, user_name, course_name, completion_date,
                                 deadline=None, session=None):
    """
    Congratulate a user who has completed a course they were assigned.

    Sent automatically by the API sync the first time a completion is detected inside
    an assignment's validity window (see app.dispatch_completion_notifications). Each
    (assignment, user) pair is emailed exactly once — the completion_notifications
    ledger in db.py guarantees it.

    Args:
        user_email (str): User's email address
        user_name (str): User's name
        course_name (str): Name of the completed course
        completion_date (str): Date the course was completed (YYYY-MM-DD)
        deadline (str, optional): The assignment deadline, shown when known
        session (SmtpSession, optional): connection to reuse across a batch

    Returns:
        SendResult: falsy if the email could not be delivered
    """
    subject = f"✅ Course Completed: {course_name}"

    # The old banner was #10b981 -> #059669; white text on the lighter end was
    # 2.54:1. Darkened one step to clear 5.4:1 while staying the same green.
    header_html = _email_header('🎉', 'Course Completed', '#047857', '#065f46')

    on_time_note = ""
    if deadline and completion_date:
        try:
            done = datetime.strptime(str(completion_date)[:10], '%Y-%m-%d')
            due = datetime.strptime(str(deadline)[:10], '%Y-%m-%d')
            if done <= due:
                on_time_note = (
                    '<p style="font-size: 14px; color: #047857; margin: 12px 0; '
                    'font-weight: 600;">🎯 Completed within the deadline — well done!</p>')
        except (ValueError, TypeError):
            on_time_note = ""

    deadline_row = ""
    if deadline:
        deadline_row = f"""
                <p style="margin: 8px 0 0 0; font-size: 14px;">
                    <strong>⏰ Deadline:</strong> {deadline}
                </p>"""

    body_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <style>
        /* Reset styles */
        body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
        table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.5;
            color: #333333;
            margin: 0;
            padding: 0;
            background-color: #f4f4f4;
        }}

        .email-container {{
            max-width: 600px;
            margin: 15px auto;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }}

        /* The banner is built by _email_header() with fully inlined colours — it
           must not depend on these rules surviving the mail client. */

        .content {{
            padding: 20px 20px;
            background: #ffffff;
        }}

        .info-box {{
            background: #ecfdf5;
            border-left: 4px solid #10b981;
            padding: 12px 15px;
            margin: 15px 0;
            border-radius: 4px;
        }}

        .footer {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-top: 1px solid #e9ecef;
            text-align: center;
        }}

        .signature {{
            margin-top: 12px;
            font-size: 13px;
            color: #495057;
            font-weight: 500;
        }}

        .footer-text {{
            font-size: 12px;
            color: #6c757d;
            line-height: 1.4;
            margin: 4px 0;
        }}

        @media only screen and (max-width: 600px) {{
            .email-container {{ margin: 10px; }}
            .content {{ padding: 15px 12px; }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        {header_html}

        <div class="content">
            <p style="font-size: 15px; color: #333333; margin-bottom: 15px;">Dear {user_name},</p>

            <p style="font-size: 14px; color: #495057; margin: 12px 0;">
                Congratulations! Our records show that you have successfully completed the
                course assigned to you.
            </p>

            <div class="info-box">
                <p style="margin: 0; font-size: 14px;">
                    <strong>📖 Course:</strong> {course_name}
                </p>
                <p style="margin: 8px 0 0 0; font-size: 14px;">
                    <strong>✅ Completed on:</strong> {completion_date or 'Recently'}
                </p>{deadline_row}
            </div>

            {on_time_note}

            <p style="font-size: 14px; color: #495057; margin: 15px 0;">
                Thank you for your commitment to safety and continuous learning. No further
                action is required for this course.
            </p>
        </div>

        <div class="footer">
            <p class="signature">
                Regards,<br>
                <strong>Safety &amp; Health Excellence Support Team</strong>
            </p>
            <p class="footer-text">
                This is an automated notification. Please do not reply to this email.
            </p>
        </div>
    </div>
</body>
</html>"""

    body_text = f"""Course Completed

Dear {user_name},

Congratulations! Our records show that you have successfully completed the course assigned to you.

📖 Course: {course_name}
✅ Completed on: {completion_date or 'Recently'}
{f'⏰ Deadline: {deadline}' if deadline else ''}

Thank you for your commitment to safety and continuous learning. No further action is required for this course.

Regards,
Safety & Health Excellence Support Team

---
This is an automated notification."""

    return send_email(user_email, subject, body_html, body_text, session=session)


def send_bulk_emails(recipients, subject, body_html, body_text=None):
    """
    Send the same email to multiple recipients over a single SMTP connection.

    Args:
        recipients (list): List of email addresses
        subject (str): Email subject
        body_html (str): HTML body content
        body_text (str, optional): Plain text body content

    Returns:
        dict: {'success': n, 'failed': n, 'failed_emails': [...],
               'failures': [{'email', 'reason', 'code', 'attempts', 'permanent'}, ...]}
        ``failures`` carries the reason per address so the caller can report *why*,
        not merely how many.
    """
    results = {'success': 0, 'failed': 0, 'failed_emails': [], 'failures': []}

    with SmtpSession() as session:
        for email in recipients:
            try:
                result = send_email(email, subject, body_html, body_text, session=session)
            except SmtpConfigError as e:
                # Credentials are wrong: every remaining address fails identically.
                logger.error(f'Aborting bulk send after {results["success"]} sent — {e}')
                for remaining in recipients[recipients.index(email):]:
                    results['failed'] += 1
                    results['failed_emails'].append(remaining)
                    results['failures'].append(
                        SendResult(False, remaining, str(e), attempts=0, permanent=True).as_dict())
                break

            if result:
                results['success'] += 1
            else:
                results['failed'] += 1
                results['failed_emails'].append(email)
                results['failures'].append(result.as_dict())

    if results['failed']:
        logger.error(f'Bulk send finished: {results["success"]} sent, {results["failed"]} failed. '
                     f'Undelivered: ' +
                     '; '.join(f'{f["email"]} [{f["reason"]}]' for f in results['failures']))
    else:
        logger.info(f'Bulk send finished: {results["success"]} sent, 0 failed')

    return results


# Template functions for common email types
def get_assignment_email_template(course_name, deadline):
    """Get HTML template for course assignment email"""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">New Course Assignment</h2>
            <p>Hello,</p>
            <p>You have been assigned a new course:</p>
            
            <div style="background: #f3f4f6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 5px 0;"><strong>Course:</strong> {course_name}</p>
                <p style="margin: 5px 0;"><strong>Deadline:</strong> {deadline}</p>
            </div>
            
            <p>Please complete this course by the deadline.</p>
            
            <p style="margin-top: 30px; color: #666; font-size: 12px;">
                This is an automated notification from the Course Analytics Dashboard.
            </p>
        </div>
    </body>
    </html>
    """


if __name__ == "__main__":
    # Run directly to check the transport config, or pass an address to send a probe:
    #   python email_service.py you@example.com
    import sys

    logging.basicConfig(
        level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    print("Email Service Module")
    print(f"SMTP Server     : {SMTP_SERVER}:{SMTP_PORT}")
    print(f"Sender          : {SENDER_ADDRESS or '(SMTP_USERNAME not set)'}")
    print(f"Rate limit      : {SMTP_RATE_PER_MIN or 'disabled'} messages/minute")
    print(f"Retry policy    : up to {SMTP_MAX_ATTEMPTS} attempt(s), "
          f"base-{SMTP_BACKOFF_BASE} backoff capped at {SMTP_BACKOFF_CAP}s")

    if len(sys.argv) > 1:
        target = sys.argv[1]
        print(f"\nSending a test message to {target} ...")
        outcome = send_email(target, 'SMTP test', '<p>SMTP transport test.</p>', 'SMTP transport test.')
        print('Result:', 'delivered' if outcome else f'FAILED — {outcome.reason}')
    else:
        print("\nReady to send notifications! "
              "(pass an address as an argument to send a test message)")
