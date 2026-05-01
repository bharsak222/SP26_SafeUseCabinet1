# Google client libraries are imported lazily inside the Gmail API send helper so
# importing this module does not fail when those optional dependencies are missing.
import os
import base64
from email.mime.text import MIMEText
from typing import Optional
import smtplib
import getpass

# This module attempts to send email via the Gmail API using OAuth2 installed-app flow.
# If the Google client libraries are not available or the user chooses not to use them,
# it can fall back to sending via SMTP (e.g. smtp.gmail.com) using credentials provided
# through environment variables `GMAIL_SMTP_USER` and `GMAIL_SMTP_PASS`.

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_paths(client_secret_path: Optional[str], token_path: Optional[str]):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if client_secret_path is None:
        client_secret_path = os.path.join(repo_root, 'client_secret_713322301011-d4s03o7k421hg8l2ddo7fr8b45ukeuc0.apps.googleusercontent.com.json')
    if token_path is None:
        token_path = os.path.join(os.path.dirname(__file__), 'token_gmail.json')
    return client_secret_path, token_path


def _send_email_gmail_api(to_address: str, subject: str, body_text: str, client_secret_path: Optional[str] = None, token_path: Optional[str] = None):
    """Send email using Gmail API. Raises ImportError if google libs are missing."""

    # Import Google client libraries lazily so importing this module doesn't fail
    # when the optional google packages are not installed.
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as e:
        raise ImportError("Google API libraries are not installed. Install them in a venv with: pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib") from e

    client_secret_path, token_path = _get_paths(client_secret_path, token_path)

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_path, 'w') as tokenf:
            tokenf.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)

    message = MIMEText(body_text)
    message['to'] = to_address
    message['from'] = 'me'
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw}
    sent = service.users().messages().send(userId='me', body=body).execute()
    return sent


def _send_email_smtp(to_address: str, subject: str, body_text: str, smtp_server: str = 'smtp.gmail.com', smtp_port: int = 587, user: Optional[str] = None, password: Optional[str] = None):
    """Send email via SMTP. Returns a dict-like result with 'smtp_sent': True on success."""
    # Prefer credentials passed explicitly, then environment variables.
    if user is None:
        user = os.environ.get('GMAIL_SMTP_USER')
    if password is None:
        password = os.environ.get('GMAIL_SMTP_PASS')
    # If credentials are not provided via env or args, try reading from an AppPassword.txt
    # file in common locations (repo root, SkeletonCode folder), then fall back to
    # prompting the user interactively.
    def _try_read_app_password_file(paths):
        for p in paths:
            try:
                if not p:
                    continue
                p = os.path.abspath(p)
                if not os.path.exists(p):
                    continue
                uname = None
                pwd = None
                with open(p, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        # Expect lines like 'Username: foo' or 'Password: bar'
                        parts = line.split(':', 1)
                        if len(parts) != 2:
                            continue
                        k = parts[0].strip().lower()
                        v = parts[1].strip()
                        if k.startswith('username') or k == 'user' or k == 'email':
                            uname = v
                        elif k.startswith('password') or k == 'pass':
                            # remove spaces in grouped app-passwords
                            pwd = v.replace(' ', '')
                if uname or pwd:
                    return uname, pwd
            except Exception:
                # ignore and try next path
                continue
        return None, None

    if not user or not password:
        # candidate locations relative to this module and repo root
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        candidates = [
            os.path.join(repo_root, 'AppPassword.txt'),
            os.path.join(repo_root, 'SkeletonCode', 'AppPassword.txt'),
            os.path.join(repo_root, 'Database', 'AppPassword.txt'),
            os.path.join(os.getcwd(), 'AppPassword.txt'),
        ]
        f_user, f_pass = _try_read_app_password_file(candidates)
        if not user and f_user:
            user = f_user
        if not password and f_pass:
            password = f_pass

    # If still missing, prompt interactively
    if not user:
        try:
            user = input('SMTP user (email address): ').strip()
        except Exception:
            user = None
    if not password:
        try:
            # use getpass so the password isn't echoed
            password = getpass.getpass('SMTP password (app password recommended): ')
        except Exception:
            password = None
    if not user or not password:
        raise RuntimeError('SMTP credentials not provided. Set GMAIL_SMTP_USER and GMAIL_SMTP_PASS environment variables or provide them interactively.')

    msg = MIMEText(body_text)
    msg['To'] = to_address
    msg['From'] = user
    msg['Subject'] = subject

    s = smtplib.SMTP(smtp_server, smtp_port)
    try:
        s.ehlo()
        s.starttls()
        try:
            s.login(user, password)
        except smtplib.SMTPAuthenticationError as auth_err:
            # Provide an actionable message for Gmail users.
            raise RuntimeError(
                "SMTP authentication failed. For Gmail, ensure 2-Step Verification is enabled and use an App Password (https://support.google.com/accounts/answer/185833). "
                f"If you prefer OAuth, install the Google client libraries in a venv and re-run. Original error: {auth_err}"
            ) from auth_err
        s.sendmail(user, [to_address], msg.as_string())
    finally:
        s.quit()
    return {'smtp_sent': True}


def send_email(to_address: str, subject: str, body_text: str, client_secret_path: Optional[str] = None, token_path: Optional[str] = None, smtp_fallback: bool = True):
    """Try to send via Gmail API; if unavailable and smtp_fallback is True, try SMTP.

    On success returns the response from Gmail API (dict) or a dict {'smtp_sent': True}.
    """
    # Allow forcing SMTP-only mode via environment variable to avoid the OAuth flow
    # (useful when the OAuth app is unverified or you prefer SMTP/App Passwords).
    # Set either FORCE_SMTP=1 or USE_SMTP=true in the environment.
    force_smtp = os.environ.get('FORCE_SMTP') or os.environ.get('USE_SMTP')
    if force_smtp and str(force_smtp).lower() in ('1', 'true', 'yes', 'y'):
        return _send_email_smtp(to_address, subject, body_text)
    # First try Gmail API path
    try:
        return _send_email_gmail_api(to_address, subject, body_text, client_secret_path, token_path)
    except Exception as e:
        # If it's an import error or runtime error indicating missing libs, optionally fall back
        msg = str(e)
        if smtp_fallback:
            try:
                return _send_email_smtp(to_address, subject, body_text)
            except Exception as smtp_e:
                # raise a combined error for visibility
                raise RuntimeError(f'Gmail API send failed ({msg}) and SMTP fallback also failed: {smtp_e}')
        # otherwise re-raise original
        raise
