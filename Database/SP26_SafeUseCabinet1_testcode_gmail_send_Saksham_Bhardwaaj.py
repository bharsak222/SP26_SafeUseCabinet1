# gmail_send.py
# Email helper for the SafeUseCabinet system.
# Provides a single public function `send_email()` that tries two paths:
#   1. Gmail API via OAuth2 (requires google-api-python-client installed in a venv)
#   2. SMTP fallback via smtp.gmail.com (requires an App Password)
#
# The Gmail API path opens a browser the first time for an OAuth consent flow and
# caches credentials in token_gmail.json for subsequent runs.
# Set FORCE_SMTP=1 or USE_SMTP=1 in the environment to skip OAuth entirely and
# go straight to the SMTP path (useful on headless Pi without a browser).
#
# App Password file (AppPassword.txt) format (searched in repo root, SkeletonCode/,
# Database/, and cwd):
#   Username: your@gmail.com
#   Password: xxxx xxxx xxxx xxxx

# Google client libraries are imported lazily inside the Gmail API send helper so
# importing this module does not fail when those optional dependencies are missing.
import os
import base64
from email.mime.text import MIMEText
from typing import Optional
import smtplib
import getpass

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _get_paths(client_secret_path: Optional[str], token_path: Optional[str]):
    """Resolve default paths for the OAuth client-secret and token files."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if client_secret_path is None:
        # Default to the client-secret JSON at the repo root
        client_secret_path = os.path.join(repo_root, 'client_secret_713322301011-d4s03o7k421hg8l2ddo7fr8b45ukeuc0.apps.googleusercontent.com.json')
    if token_path is None:
        # Cache the OAuth token next to this module so it survives restarts
        token_path = os.path.join(os.path.dirname(__file__), 'token_gmail.json')
    return client_secret_path, token_path


def _send_email_gmail_api(to_address: str, subject: str, body_text: str,
                          client_secret_path: Optional[str] = None,
                          token_path: Optional[str] = None):
    """
    Send email using the Gmail REST API with OAuth2 installed-app credentials.
    Raises ImportError if the google-api-python-client packages are not installed.
    On first run opens a browser to complete the OAuth consent flow; subsequent
    runs use the cached token in token_gmail.json.
    """
    # Lazy import so the module loads even without the google packages installed
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as e:
        raise ImportError(
            "Google API libraries are not installed. "
            "Install them in a venv with: pip install --upgrade "
            "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from e

    client_secret_path, token_path = _get_paths(client_secret_path, token_path)

    creds = None
    # Load cached credentials if available
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # Refresh or re-authorize if credentials are missing or expired
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # Silent refresh using the stored refresh token
        else:
            # First-time auth: opens a local browser window for the consent screen
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        # Persist credentials for future runs
        with open(token_path, 'w') as tokenf:
            tokenf.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)

    # Build the MIME message and base64-encode it for the Gmail API
    message = MIMEText(body_text)
    message['to'] = to_address
    message['from'] = 'me'
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    body = {'raw': raw}
    sent = service.users().messages().send(userId='me', body=body).execute()
    return sent


def _send_email_smtp(to_address: str, subject: str, body_text: str,
                     smtp_server: str = 'smtp.gmail.com', smtp_port: int = 587,
                     user: Optional[str] = None, password: Optional[str] = None):
    """
    Send email via SMTP with STARTTLS. Returns {'smtp_sent': True} on success.
    Credential resolution order:
      1. Explicit user/password arguments
      2. GMAIL_SMTP_USER / GMAIL_SMTP_PASS environment variables
      3. AppPassword.txt file searched in common locations
      4. Interactive prompt (stdin)
    For Gmail, an App Password is required (not the account password) when
    2-Step Verification is enabled.
    """
    # Prefer explicitly-passed credentials over environment variables
    if user is None:
        user = os.environ.get('GMAIL_SMTP_USER')
    if password is None:
        password = os.environ.get('GMAIL_SMTP_PASS')

    def _try_read_app_password_file(paths):
        """
        Try reading credentials from an AppPassword.txt file at each path.
        Expected format: lines of "Key: value" (Username/Password).
        Returns (user, password) — either may be None if not found.
        """
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
                        parts = line.split(':', 1)
                        if len(parts) != 2:
                            continue
                        k = parts[0].strip().lower()
                        v = parts[1].strip()
                        if k.startswith('username') or k == 'user' or k == 'email':
                            uname = v
                        elif k.startswith('password') or k == 'pass':
                            # App passwords contain spaces in groups — remove them
                            pwd = v.replace(' ', '')
                if uname or pwd:
                    return uname, pwd
            except Exception:
                continue  # Try the next candidate path
        return None, None

    if not user or not password:
        # Search common locations for an AppPassword.txt credential file
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

    # Fall back to interactive prompt if credentials still missing
    if not user:
        try:
            user = input('SMTP user (email address): ').strip()
        except Exception:
            user = None
    if not password:
        try:
            # getpass hides the password from the terminal
            password = getpass.getpass('SMTP password (app password recommended): ')
        except Exception:
            password = None
    if not user or not password:
        raise RuntimeError(
            'SMTP credentials not provided. Set GMAIL_SMTP_USER and GMAIL_SMTP_PASS '
            'environment variables or provide them interactively.'
        )

    msg = MIMEText(body_text)
    msg['To']      = to_address
    msg['From']    = user
    msg['Subject'] = subject

    s = smtplib.SMTP(smtp_server, smtp_port)
    try:
        s.ehlo()
        s.starttls()  # Upgrade connection to TLS before sending credentials
        try:
            s.login(user, password)
        except smtplib.SMTPAuthenticationError as auth_err:
            raise RuntimeError(
                "SMTP authentication failed. For Gmail, ensure 2-Step Verification is "
                "enabled and use an App Password (https://support.google.com/accounts/answer/185833). "
                f"If you prefer OAuth, install the Google client libraries in a venv and re-run. "
                f"Original error: {auth_err}"
            ) from auth_err
        s.sendmail(user, [to_address], msg.as_string())
    finally:
        s.quit()  # Always close the SMTP connection
    return {'smtp_sent': True}


def send_email(to_address: str, subject: str, body_text: str,
               client_secret_path: Optional[str] = None,
               token_path: Optional[str] = None,
               smtp_fallback: bool = True):
    """
    Send an email to to_address with the given subject and plain-text body.
    Tries the Gmail API first; if unavailable (missing libraries, expired token,
    unverified app) and smtp_fallback is True, retries via SMTP.
    Set FORCE_SMTP=1 or USE_SMTP=1 to skip OAuth and use SMTP only.
    Returns the Gmail API response dict or {'smtp_sent': True} on SMTP success.
    """
    # Honor an environment-variable override to skip OAuth entirely
    force_smtp = os.environ.get('FORCE_SMTP') or os.environ.get('USE_SMTP')
    if force_smtp and str(force_smtp).lower() in ('1', 'true', 'yes', 'y'):
        return _send_email_smtp(to_address, subject, body_text)

    # Primary path: Gmail API via OAuth2
    try:
        return _send_email_gmail_api(to_address, subject, body_text, client_secret_path, token_path)
    except Exception as e:
        msg = str(e)
        if smtp_fallback:
            # Secondary path: SMTP with App Password
            try:
                return _send_email_smtp(to_address, subject, body_text)
            except Exception as smtp_e:
                # Both paths failed — surface a combined error
                raise RuntimeError(
                    f'Gmail API send failed ({msg}) and SMTP fallback also failed: {smtp_e}'
                )
        raise  # No fallback requested — re-raise original exception
