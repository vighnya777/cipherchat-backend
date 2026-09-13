from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cipherchat import db
import secrets
import string
import pytz

# Indian Standard Time (IST)
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    """Get current time in Indian Standard Time"""
    return datetime.now(IST).replace(tzinfo=None)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))
    phone = db.Column(db.String(20))
    bio = db.Column(db.Text)
    profile_picture = db.Column(db.String(255))
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(100))
    avatar_url = db.Column(db.String(500))
    is_admin = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    last_login = db.Column(db.DateTime)
    last_profile_update = db.Column(db.DateTime)
    
    # User ban/block fields
    is_banned = db.Column(db.Boolean, default=False, index=True)
    banned_at = db.Column(db.DateTime)  # When the ban was applied (UTC)
    ban_expires_at = db.Column(db.DateTime)  # When the ban expires (None = permanent)
    ban_reason = db.Column(db.Text)  # Reason for the ban
    banned_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Admin who banned the user
    
    # Account status: 'active' or 'deleted'
    account_status = db.Column(db.String(20), default='active', index=True)
    
    # Two-Factor Authentication - Authenticator app (TOTP, RFC 6238)
    totp_secret = db.Column(db.String(64))          # base32 secret, only set once enabled
    totp_enabled = db.Column(db.Boolean, default=False)
    totp_enabled_at = db.Column(db.DateTime)
    totp_backup_codes = db.Column(db.Text)           # JSON array of hashed one-time backup codes

    # OTP fields
    otp_code = db.Column(db.String(10))
    otp_expires_at = db.Column(db.DateTime)
    last_otp_sent_at = db.Column(db.DateTime)  # Track when OTP was last sent for rate limiting
    otp_resend_attempt_count = db.Column(db.Integer, default=0)  # Track resend attempts for exponential backoff
    
    # Admin OTP resend rate limiting - separate from user OTP to prevent correlation
    admin_otp_resend_count = db.Column(db.Integer, default=0)  # Track admin OTP resend attempts
    admin_last_otp_sent_at = db.Column(db.DateTime)  # Track when admin OTP was last sent
    admin_otp_lockout_until = db.Column(db.DateTime)  # Admin OTP rate limit lockout
    
    # Backup codes for OTP recovery (JSON format: hashed codes)
    backup_codes = db.Column(db.Text)  # JSON array of hashed backup codes
    backup_codes_generated_at = db.Column(db.DateTime)  # When backup codes were last generated
    
    # Rate limit confirmation fields
    rate_limit_lockout_until = db.Column(db.DateTime)
    rate_limit_confirmation_token = db.Column(db.String(128), index=True)
    rate_limit_confirmation_expires = db.Column(db.DateTime)
    rate_limit_confirmed = db.Column(db.Boolean, default=False)
    
    # Profile completion reminder settings
    profile_completion_email_enabled = db.Column(db.Boolean, default=True)
    last_profile_reminder_email = db.Column(db.DateTime)
    profile_completion_percentage = db.Column(db.Integer, default=0)
    
    # Form Creator access control
    is_form_creator = db.Column(db.Boolean, default=False, index=True)
    form_creator_approved_at = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_otp(self):
        self.otp_code = ''.join(secrets.choice(string.digits) for _ in range(6))
        self.otp_expires_at = get_ist_now().replace(microsecond=0) + timedelta(minutes=10)
        return self.otp_code
 
    def verify_otp(self, otp):
        """
        Securely verify OTP with:
        - Format validation (must be 6 digits)
        - Expiration time checks
        - Constant-time comparison to prevent timing attacks
        """
        # Validate input format
        if not otp or not isinstance(otp, str):
            return False
        
        # Strip whitespace and validate format
        otp = otp.strip()
        if not otp.isdigit() or len(otp) != 6:
            return False
        
        # Check if OTP code exists and is not expired
        if not self.otp_code or not self.otp_expires_at:
            return False
        
        now = get_ist_now()
        if now > self.otp_expires_at:
            return False
        
        # Use constant-time comparison to prevent timing attacks
        import hmac
        return hmac.compare_digest(self.otp_code, otp)
    
    def clear_otp(self):
        self.otp_code = None
        self.otp_expires_at = None
    
    def get_otp_resend_wait_seconds(self):
        """
        Calculate exponential backoff wait time in seconds.
        
        Formula: base_seconds * (2 ^ attempt_count)
        - Attempt 0 (1st resend): 60 * (2^0) = 60 seconds
        - Attempt 1 (2nd resend): 60 * (2^1) = 120 seconds
        - Attempt 2 (3rd resend): 60 * (2^2) = 240 seconds
        - Attempt 3 (4th resend): 60 * (2^3) = 480 seconds
        
        The attempt counter resets if no OTP was requested in the last 24 hours.
        """
        base_seconds = 60  # Start with 60 seconds
        
        # Check if we should reset the counter (24 hours since last OTP)
        if self.last_otp_sent_at:
            time_since_last_send = (get_ist_now() - self.last_otp_sent_at).total_seconds()
            if time_since_last_send > (24 * 3600):  # More than 24 hours
                # Reset counter
                self.otp_resend_attempt_count = 0
        
        # Calculate exponential backoff: base * (2 ^ attempt_count)
        wait_seconds = base_seconds * (2 ** self.otp_resend_attempt_count)
        
        # Cap at 24 hours to prevent unreasonably long wait times
        max_wait = 24 * 3600
        return min(wait_seconds, max_wait)
    
    def can_resend_admin_otp(self):
        """
        Check if admin can resend OTP.
        Returns: (can_resend: bool, wait_seconds: int, message: str)
        """
        now = get_ist_now()
        
        # Check if currently locked out
        if self.admin_otp_lockout_until:
            if now < self.admin_otp_lockout_until:
                wait_seconds = int((self.admin_otp_lockout_until - now).total_seconds())
                return False, wait_seconds, f"Too many resend attempts. Please wait {wait_seconds} seconds."
            else:
                # Lockout expired, reset counters
                self.admin_otp_lockout_until = None
                self.admin_otp_resend_count = 0
        
        # Check if OTP was sent less than 60 seconds ago
        if self.admin_last_otp_sent_at:
            time_since_last = (now - self.admin_last_otp_sent_at).total_seconds()
            if time_since_last < 60:
                wait_seconds = int(60 - time_since_last)
                return False, wait_seconds, f"Please wait {wait_seconds} seconds before requesting a new OTP."
        
        return True, 0, "OTP can be resent."
    
    def get_admin_otp_resend_wait_seconds(self):
        """
        Calculate wait time for admin OTP resend with rate limiting.
        Returns seconds to wait before next resend is allowed.
        """
        now = get_ist_now()
        
        # Check lockout
        if self.admin_otp_lockout_until and now < self.admin_otp_lockout_until:
            return int((self.admin_otp_lockout_until - now).total_seconds())
        
        # Check time since last send
        if self.admin_last_otp_sent_at:
            time_since_last = (now - self.admin_last_otp_sent_at).total_seconds()
            if time_since_last < 60:
                return int(60 - time_since_last)
        
        return 0
    
    def record_admin_otp_resend_attempt(self):
        """Record an admin OTP resend attempt and apply rate limiting if needed."""
        now = get_ist_now()
        
        # Increment resend counter
        self.admin_otp_resend_count = (self.admin_otp_resend_count or 0) + 1
        self.admin_last_otp_sent_at = now
        
        # Apply exponential backoff lockout after 5 attempts
        # Attempt 5+: Lock for 5 minutes
        # Attempt 6+: Lock for 10 minutes
        # Attempt 7+: Lock for 20 minutes
        if self.admin_otp_resend_count >= 7:
            lockout_minutes = 20
        elif self.admin_otp_resend_count >= 6:
            lockout_minutes = 10
        elif self.admin_otp_resend_count >= 5:
            lockout_minutes = 5
        else:
            lockout_minutes = 0
        
        if lockout_minutes > 0:
            self.admin_otp_lockout_until = now + timedelta(minutes=lockout_minutes)
    
    def reset_admin_otp_resend_tracking(self):
        """Reset admin OTP resend tracking after successful verification."""
        self.admin_otp_resend_count = 0
        self.admin_last_otp_sent_at = None
        self.admin_otp_lockout_until = None
    
    def validate_admin_otp(self, otp):
        """
        Comprehensive admin OTP validation with enhanced security checks.
        Returns: (is_valid: bool, error_message: str)
        
        Validates:
        - OTP format (6 digits)
        - OTP expiration
        - OTP code match (constant-time comparison)
        """
        # Validate input format
        if not otp or not isinstance(otp, str):
            return False, "Invalid OTP format."
        
        # Strip and validate
        otp = otp.strip()
        if not otp.isdigit():
            return False, "OTP must contain only digits."
        
        if len(otp) != 6:
            return False, "OTP must be exactly 6 digits."
        
        # Check if OTP exists
        if not self.otp_code:
            return False, "No active OTP found. Please request a new one."
        
        # Check expiration
        if not self.otp_expires_at:
            return False, "OTP configuration error. Please request a new one."
        
        now = get_ist_now()
        # Calculate time remaining
        time_remaining = (self.otp_expires_at - now).total_seconds()
        expires_in_seconds = int(time_remaining)
        
        # Check if expired (time_remaining is negative or zero)
        if time_remaining <= 0:
            minutes = abs(int(time_remaining // 60))
            return False, f"OTP expired {minutes} minutes ago. Please request a new one."
        
        # Constant-time comparison to prevent timing attacks
        import hmac
        if hmac.compare_digest(self.otp_code, otp):
            return True, ""
        
        return False, f"Incorrect OTP. Please try again. (Expires in {expires_in_seconds} seconds)"
    
    def get_otp_expiration_countdown(self):
        """
        Get remaining seconds for OTP expiration.
        Returns: (seconds_remaining: int, is_expired: bool)
        """
        if not self.otp_expires_at:
            return 0, True
        
        now = get_ist_now()
        remaining = (self.otp_expires_at - now).total_seconds()
        
        if remaining <= 0:
            return 0, True
        
        return int(remaining), False
    
    # ============================================================================
    # BACKUP CODES FOR OTP RECOVERY
    # ============================================================================
    
    def generate_backup_codes(self, count=10):
        """
        Generate backup codes for OTP recovery.
        Returns a list of plaintext codes that should be shown to user once.
        
        Args:
            count: Number of backup codes to generate (default: 10)
        
        Returns:
            List of backup codes in format: XXXX-XXXX-XXXX (12 characters)
        """
        import json
        import hmac
        
        backup_codes_list = []
        hashed_codes = []
        
        for _ in range(count):
            # Generate backup code: XXXX-XXXX-XXXX format
            code = '-'.join([
                ''.join(secrets.choice(string.digits + string.ascii_uppercase) for _ in range(4))
                for _ in range(3)
            ])
            backup_codes_list.append(code)
            
            # Hash the code before storing
            hashed = hmac.new(
                b'backup_code_secret',
                code.encode(),
                'sha256'
            ).hexdigest()
            hashed_codes.append(hashed)
        
        # Store hashed codes as JSON
        self.backup_codes = json.dumps(hashed_codes)
        self.backup_codes_generated_at = get_ist_now()
        
        return backup_codes_list
    
    def validate_backup_code(self, code):
        """
        Validate and consume a backup code.
        
        Args:
            code: The backup code to validate
        
        Returns:
            Tuple: (is_valid: bool, remaining_codes: int, error_message: str)
        """
        import json
        import hmac
        
        if not self.backup_codes:
            return False, 0, "No backup codes available."
        
        try:
            hashed_codes = json.loads(self.backup_codes)
        except json.JSONDecodeError:
            return False, 0, "Backup codes configuration error."
        
        if not hashed_codes:
            return False, 0, "All backup codes have been used."
        
        # Hash the provided code
        provided_hash = hmac.new(
            b'backup_code_secret',
            code.strip().encode(),
            'sha256'
        ).hexdigest()
        
        # Use constant-time comparison
        for i, stored_hash in enumerate(hashed_codes):
            if hmac.compare_digest(provided_hash, stored_hash):
                # Code is valid - remove it from the list
                hashed_codes.pop(i)
                self.backup_codes = json.dumps(hashed_codes)
                
                return True, len(hashed_codes), ""
        
        return False, len(hashed_codes), "Invalid backup code."
    
    def get_backup_codes_count(self):
        """Get the number of remaining unused backup codes."""
        import json
        
        if not self.backup_codes:
            return 0
        
        try:
            codes = json.loads(self.backup_codes)
            return len(codes)
        except json.JSONDecodeError:
            return 0
    
    def clear_backup_codes(self):
        """Clear all backup codes."""
        self.backup_codes = None
        self.backup_codes_generated_at = None
    
    def is_currently_banned(self):
        """Check if the user is currently banned (active or temporary)."""
        if not self.is_banned:
            return False
        
        if self.ban_expires_at:
            # Make both datetimes timezone-aware for comparison
            expiry = self.ban_expires_at
            if expiry.tzinfo is None:
                # If stored datetime is naive, assume it's UTC
                expiry = expiry.replace(tzinfo=pytz.UTC)
            
            current_time = datetime.now(pytz.UTC)
            if current_time > expiry:
                # Ban has expired, auto-unban
                self.is_banned = False
                self.ban_expires_at = None
                return False
        
        return True
    
    def get_ban_message(self):
        """Get the appropriate ban message for the user."""
        if not self.is_currently_banned():
            return None
        
        message = "You are banned from this platform."
        if self.ban_reason:
            message += f" Reason: {self.ban_reason}"
        if self.ban_expires_at:
            ban_time_utc = self.ban_expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            message += f" Ban active until {ban_time_utc}"
        else:
            message += " This is a permanent ban."
        return message
    
    def can_login(self):
        """Check if user can login (not banned, not deleted)."""
        if self.account_status == 'deleted':
            return False
        return not self.is_currently_banned()
    
    @property
    def full_name(self):
        """Return the user's preferred display name."""
        parts = []
        if self.first_name:
            parts.append(self.first_name.strip())
        if self.last_name:
            parts.append(self.last_name.strip())
        name = ' '.join(parts).strip()
        if name:
            return name
        return self.username
    
    @staticmethod
    def create_oauth_user(email, username, provider, oauth_id, avatar_url=None):
        # Always store normalized email to prevent case-variant duplicates
        normalized = (email or '').strip().lower()
        user = User(
            username=username,
            email=normalized,
            password_hash='',
            oauth_provider=provider,
            oauth_id=str(oauth_id),
            avatar_url=avatar_url,
            is_verified=True,
            is_active=True,
            account_status='active',
        )
        return user

class FeedbackSubject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_ist_now)

class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

class SystemConfig(db.Model):
    """
    Backing table for the System Settings admin module (app/settings/).

    One row per setting key. Referenced via app.settings.models.get_model()
    — see app/settings/service.py and app/settings/migrate.py for the
    read/write API and table-creation/seeding logic.
    """
    __tablename__ = 'system_config'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    is_encrypted = db.Column(db.Boolean, default=False)
    group = db.Column(db.String(50), default='general')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(150))

class FeedbackForm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    slug = db.Column(db.String(150), nullable=False, index=True)  # No longer globally unique
    form_type = db.Column(db.String(20), default='admin')  # 'admin' or 'user'
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    visibility = db.Column(db.String(20), default='public')  # 'public' or 'private'
    expires_at = db.Column(db.DateTime, nullable=True)  # Form expiry date
    version = db.Column(db.Integer, default=1)  # Form schema version
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Track who created the form
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Relationships
    fields = db.relationship('FormField', backref='form', lazy='select', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.UniqueConstraint('slug', 'form_type', 'created_by_id', name='unique_form_per_user'),
    )

# Association table for many-to-many relationship between Feedback and FileStorage
feedback_files_association = db.Table(
    'feedback_files_association',
    db.Column('feedback_id', db.Integer, db.ForeignKey('feedback.id'), primary_key=True),
    db.Column('file_id', db.Integer, db.ForeignKey('file_storage.id'), primary_key=True),
    db.Column('added_at', db.DateTime, default=get_ist_now)
)

class FormSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    
    # File uploads disabled by default - must be explicitly enabled by admin
    allow_file_uploads = db.Column(db.Boolean, default=False)
    max_files_per_submission = db.Column(db.Integer, default=5)
    max_file_size_mb = db.Column(db.Integer, default=10)
    require_file_upload = db.Column(db.Boolean, default=False)
    require_user_login = db.Column(db.Boolean, default=False)
    allow_anonymous_submissions = db.Column(db.Boolean, default=True)
    enable_captcha = db.Column(db.Boolean, default=False)
    captcha_version = db.Column(db.String(10), default='v3', index=True)  # 'v2' or 'v3'
    auto_respond = db.Column(db.Boolean, default=True)
    send_admin_notification = db.Column(db.Boolean, default=True)
    enable_rating_system = db.Column(db.Boolean, default=True)
    enable_subject_selection = db.Column(db.Boolean, default=True)
    enable_additional_fields = db.Column(db.Boolean, default=True)
    enable_restore_fields = db.Column(db.Boolean, default=False)
    
    custom_success_message = db.Column(db.Text)
    custom_error_message = db.Column(db.Text)
    custom_form_description = db.Column(db.Text)  # Optional custom description for form (replaces default)
    redirect_url = db.Column(db.String(500))
    
    custom_css = db.Column(db.Text)
    custom_logo_url = db.Column(db.String(500))
    theme_color = db.Column(db.String(50), default='#3B82F6')
    
    allowed_file_types = db.Column(db.String(500))  # Comma-separated format: "images,documents,pdf"
    
    # Custom upload section configuration
    upload_section_label = db.Column(db.String(200), default='Upload Files')  # Customizable label for upload section
    
    # Custom upload fields - JSON format for flexible field configuration
    custom_upload_fields = db.Column(db.Text, default='[]')  # JSON array of custom upload field names
    
    # Auto-email settings
    auto_email_enabled = db.Column(db.Boolean, default=False)
    auto_email_recipients = db.Column(db.Text)  # Comma-separated email addresses
    
    # Ticket system
    enable_tickets = db.Column(db.Boolean, default=True)  # Auto-generate ticket IDs on submission
    ticket_prefix = db.Column(db.String(10), default='')  # Optional prefix for ticket IDs
    
    # Form submission limits - time-based rate limiting per form
    enable_submission_limit = db.Column(db.Boolean, default=False)  # Enable submission time-based limits
    submission_limit_count = db.Column(db.Integer, default=1)  # Number of submissions allowed
    submission_limit_period_minutes = db.Column(db.Integer, default=60)  # Time period in minutes
    # e.g., enable_submission_limit=True, submission_limit_count=3, submission_limit_period_minutes=60 = 3 submissions per hour
    # Limit mode: 'once' = one submission ever, 'daily' = once per day, 'unlimited' = no limit (ignore enable flag)
    submission_limit_type = db.Column(db.String(20), default='time_window')  # 'once', 'daily', 'time_window', 'unlimited' 
    
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    def get_allowed_file_extensions(self):
        """Get list of allowed file extensions."""
        if self.allowed_file_types_list:
            extensions = []
            for category, exts in self.allowed_file_types_list.items():
                extensions.extend(exts)
            return extensions
        elif self.allowed_file_types:
            # Parse legacy format
            types_map = {
                'images': ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'],
                'documents': ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt'],
                'spreadsheets': ['xls', 'xlsx', 'csv', 'ods'],
                'presentations': ['ppt', 'pptx', 'odp'],
                'archives': ['zip', 'rar', '7z', 'tar', 'gz'],
                'audio': ['mp3', 'wav', 'flac', 'aac', 'm4a'],
                'video': ['mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'],
                'code': ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'json'],
                'executables': ['exe', 'msi', 'dmg', 'app']
            }
            types = self.allowed_file_types.split(',')
            extensions = []
            for t in types:
                extensions.extend(types_map.get(t.strip(), []))
            return extensions
        return []
    
    def get_custom_upload_fields(self):
        """Get list of custom upload fields from JSON"""
        if not self.custom_upload_fields:
            return []
        try:
            import json
            return json.loads(self.custom_upload_fields)
        except:
            return []
    
    def set_custom_upload_fields(self, fields):
        """Set custom upload fields from list"""
        import json
        if isinstance(fields, list):
            self.custom_upload_fields = json.dumps(fields)
        else:
            self.custom_upload_fields = '[]'
    
    def add_custom_upload_field(self, field_name):
        """Add a single custom upload field"""
        import json
        fields = self.get_custom_upload_fields()
        if field_name and field_name not in fields:
            fields.append(field_name)
            self.custom_upload_fields = json.dumps(fields)
            return True
        return False
    
    def remove_custom_upload_field(self, field_name):
        """Remove a custom upload field"""
        import json
        fields = self.get_custom_upload_fields()
        if field_name in fields:
            fields.remove(field_name)
            self.custom_upload_fields = json.dumps(fields)
            return True
        return False

class FormFieldSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    field_name = db.Column(db.String(100), nullable=False)
    is_required = db.Column(db.Boolean, default=False)
    is_visible = db.Column(db.Boolean, default=True)
    custom_label = db.Column(db.String(200))
    custom_placeholder = db.Column(db.String(200))
    custom_validation_message = db.Column(db.Text)
    field_order = db.Column(db.Integer, default=0)
    field_group = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    preferences = db.Column(db.JSON)
    notifications_enabled = db.Column(db.Boolean, default=True)
    email_notifications = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

class FileStorage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer)
    storage_path = db.Column(db.String(500), nullable=False)
    cloud_storage_path = db.Column(db.String(500))  # Path in cloud storage
    cloud_storage_id = db.Column(db.String(255))  # Enhanced cloud storage ID
    cloud_metadata = db.Column(db.Text)  # JSON metadata from enhanced cloud storage
    is_cloud_stored = db.Column(db.Boolean, default=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    uploaded_at = db.Column(db.DateTime, default=get_ist_now)
    is_public = db.Column(db.Boolean, default=False)
    scanned_for_viruses = db.Column(db.Boolean, default=False)
    virus_scan_result = db.Column(db.String(100))

class SecurityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    risk_level = db.Column(db.String(20), default='low')
    created_at = db.Column(db.DateTime, default=get_ist_now)

class NotificationSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    notification_type = db.Column(db.String(100), nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    email_enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

class LoginHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    login_time = db.Column(db.DateTime, default=get_ist_now)
    ip_address = db.Column(db.String(45))
    device_fingerprint = db.Column(db.String(128), index=True)
    user_agent = db.Column(db.String(500))
    browser = db.Column(db.String(100))
    browser_version = db.Column(db.String(50))
    os = db.Column(db.String(100))
    os_version = db.Column(db.String(50))
    device_type = db.Column(db.String(50))
    location = db.Column(db.Text)  # JSON blob: {country, region, city, timezone, latitude, longitude, source, isp}
    city = db.Column(db.String(120))
    region = db.Column(db.String(120))
    country = db.Column(db.String(120))
    timezone = db.Column(db.String(80))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_source = db.Column(db.String(20))  # 'GPS' or 'IP Approximation'
    device_info = db.Column(db.String(500))
    is_new_device = db.Column(db.Boolean, default=False)
    login_method = db.Column(db.String(20))

class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer)
    status = db.Column(db.String(20), default='new', index=True)
    subject = db.Column(db.String(100))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    admin_reply = db.Column(db.Text)
    replied_at = db.Column(db.DateTime)
    
    # Form versioning
    form_version = db.Column(db.Integer, default=1)  # Schema version used for this submission

    # Foreign keys
    replied_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=True, index=True)

    # Additional dynamic fields stored as JSON
    additional_data = db.Column(db.JSON)
    
    # Internal notes (admin-only)
    internal_notes = db.Column(db.Text)

    # Relationships
    replied_by_user = db.relationship(
        'User',
        foreign_keys=[replied_by]
    )
    user = db.relationship(
        'User',
        foreign_keys=[user_id]
    )
    form = db.relationship(
        'FeedbackForm',
        foreign_keys=[form_id],
        backref=db.backref('feedbacks', lazy='dynamic')
    )
    
    # File relationship with cascade so deleting Feedback deletes its files too
    files = db.relationship(
        'FeedbackFile',
        foreign_keys='FeedbackFile.feedback_id',
        cascade='all, delete-orphan',
        lazy='dynamic',
        overlaps='attached_files,feedback'
    )

    # Reply history relationship
    reply_history = db.relationship(
        'FeedbackReply',
        backref='parent_feedback',
        lazy='dynamic',
        order_by='FeedbackReply.sent_at.desc()',
        cascade='all, delete-orphan'
    )

class FormField(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=True, index=True)
    field_name = db.Column(db.String(50), nullable=False)
    field_type = db.Column(db.String(30), nullable=False)  # text, textarea, email, number, date, time, timing, link, select, multi-select, checkbox, radio, file, code, richtext, captcha, url, currency, slider, toggle, signature, color, phone, country, mcq, rating, terms_checkbox, device, college_selector
    field_label = db.Column(db.String(100), nullable=False)
    field_placeholder = db.Column(db.String(100))
    field_options = db.Column(db.JSON)
    is_required = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)
    validation_pattern = db.Column(db.String(100000))
    min_length = db.Column(db.Integer)
    max_length = db.Column(db.Integer)
    
    # File upload specific fields
    allowed_file_types = db.Column(db.String(500))
    max_file_size_mb = db.Column(db.Integer, default=10)
    max_files = db.Column(db.Integer, default=1)
    
    # Rich text and code block specific
    default_value = db.Column(db.Text)  # For code blocks, rich text, etc.
    
    # Slider, range, and numeric fields
    min_value = db.Column(db.Float)
    max_value = db.Column(db.Float)
    step_value = db.Column(db.Float, default=1)
    
    # Currency field
    currency_symbol = db.Column(db.String(5), default='$')
    currency_code = db.Column(db.String(3), default='USD')
    
    # Signature field
    signature_bg_color = db.Column(db.String(7), default='#FFFFFF')
    signature_pad_width = db.Column(db.Integer, default=500)
    signature_pad_height = db.Column(db.Integer, default=200)
    
    # Color picker
    color_format = db.Column(db.String(10), default='hex')  # hex, rgb, hsl
    
    # Time field
    time_format = db.Column(db.String(10), default='24h')  # 24h or 12h
    
    def __init__(self, **kwargs):
        super(FormField, self).__init__(**kwargs)
        # Strip whitespace from string fields
        if self.field_name:
            self.field_name = self.field_name.strip()
        if self.field_label:
            self.field_label = self.field_label.strip()
        if self.field_placeholder:
            self.field_placeholder = self.field_placeholder.strip()
    
    @property
    def options_list(self):
        return self.field_options or []

class Channel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    link = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=get_ist_now)

class AdminLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=get_ist_now)
    
    # Relationship
    admin = db.relationship('User', backref='admin_logs')


class AuditLog(db.Model):
    """Audit log for tracking admin actions on users (block, unblock, delete)."""
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)  # NULL for system/automatic actions
    action = db.Column(db.String(50), nullable=False, index=True)  # 'block', 'unblock', 'delete', 'restore'
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    reason = db.Column(db.Text)
    ban_duration_days = db.Column(db.Integer)  # NULL for permanent bans
    ban_expires_at = db.Column(db.DateTime)  # When the ban expires (UTC)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    
    # Relationships
    admin = db.relationship('User', foreign_keys=[admin_id], backref='audit_actions_performed')
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='audit_actions_against')
    
    def __repr__(self):
        return f'<AuditLog action={self.action} admin_id={self.admin_id} target_user_id={self.target_user_id}>'

class FeedbackReply(db.Model):
    """Track reply history for feedback submissions."""
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False, index=True)
    reply_text = db.Column(db.Text, nullable=False)
    sent_to_email = db.Column(db.String(120))  # Email address reply was sent to
    sent_at = db.Column(db.DateTime, default=get_ist_now)
    sent_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email_sent = db.Column(db.Boolean, default=False)  # Whether email was successfully sent
    
    # Relationships - using overlaps to avoid warning
    feedback = db.relationship('Feedback', foreign_keys=[feedback_id], overlaps="parent_feedback,reply_history")
    sender = db.relationship('User', foreign_keys=[sent_by])

class FeedbackFile(db.Model):
    """Model for files attached to feedback submissions."""
    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer)
    storage_path = db.Column(db.String(500), nullable=False)
    cloud_storage_path = db.Column(db.String(500))  # Path in cloud storage (MinIO/S3)
    is_cloud_stored = db.Column(db.Boolean, default=False)  # Whether stored in cloud
    uploaded_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    scanned_for_viruses = db.Column(db.Boolean, default=False)  # Whether file was scanned
    virus_scan_result = db.Column(db.String(100))  # 'clean', 'infected', 'error'
    
    # Relationships
    feedback = db.relationship('Feedback', backref='attached_files', foreign_keys=[feedback_id], overlaps='files')
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

# ============= GOOGLE FORMS-LIKE FEATURES =============

class FormTheme(db.Model):
    """Store form themes and styling options"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True, unique=True)
    
    # Theme colors
    primary_color = db.Column(db.String(50), default='#3B82F6')
    secondary_color = db.Column(db.String(50), default='#1F2937')
    accent_color = db.Column(db.String(50), default='#10B981')
    background_color = db.Column(db.String(50), default='#F9FAFB')
    text_color = db.Column(db.String(50), default='#111827')
    
    # Background image
    background_image_url = db.Column(db.String(500))
    
    # Font and spacing
    font_family = db.Column(db.String(100), default='sans-serif')
    border_radius = db.Column(db.Integer, default=8)  # in pixels
    
    # Header section
    header_background_color = db.Column(db.String(50))
    header_text_color = db.Column(db.String(50))
    
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    form = db.relationship('FeedbackForm', backref='theme')


class FormBranching(db.Model):
    """Store conditional branching logic for forms (skip logic)"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    source_field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'), nullable=False)  # Field that triggers logic
    
    # Condition
    condition_type = db.Column(db.String(50), nullable=False)  # 'equals', 'contains', 'greater_than', 'less_than'
    condition_value = db.Column(db.Text, nullable=False)
    
    # Action
    target_field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'))  # Field to show/hide
    action_type = db.Column(db.String(50), nullable=False)  # 'show', 'hide', 'skip_to'
    skip_to_field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'))  # For skip_to action
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    
    source_field = db.relationship('FormField', foreign_keys=[source_field_id])
    target_field = db.relationship('FormField', foreign_keys=[target_field_id])
    skip_field = db.relationship('FormField', foreign_keys=[skip_to_field_id])


class FormSection(db.Model):
    """Group form fields into sections/pages"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    section_type = db.Column(db.String(50), default='section')  # 'section' or 'page'
    order_index = db.Column(db.Integer, default=0)
    
    # Section styling
    background_color = db.Column(db.String(50))
    text_color = db.Column(db.String(50))
    show_section_number = db.Column(db.Boolean, default=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    form = db.relationship('FeedbackForm', backref='sections')


class FormResponse(db.Model):
    """Store form responses (can have multiple responses per feedback)"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey('feedback.id'), nullable=True)
    
    # Response metadata
    respondent_email = db.Column(db.String(120))
    respondent_name = db.Column(db.String(100))
    respondent_ip = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    
    # Timing
    started_at = db.Column(db.DateTime, default=get_ist_now)
    completed_at = db.Column(db.DateTime)
    time_spent_seconds = db.Column(db.Integer)  # Duration to complete
    
    # Response status
    is_draft = db.Column(db.Boolean, default=False)
    is_completed = db.Column(db.Boolean, default=False)
    completion_percentage = db.Column(db.Integer, default=0)
    
    # Response data - stored as JSON
    responses = db.Column(db.JSON, default={})  # {field_id: answer}
    
    # Metadata
    device_type = db.Column(db.String(50))  # desktop, mobile, tablet
    location = db.Column(db.String(200))
    
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    form = db.relationship('FeedbackForm', backref='responses')
    feedback = db.relationship('Feedback', backref='form_responses')


class FormAnalytics(db.Model):
    """Track form analytics and statistics"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True, unique=True)
    
    # Response statistics
    total_responses = db.Column(db.Integer, default=0)
    completed_responses = db.Column(db.Integer, default=0)
    draft_responses = db.Column(db.Integer, default=0)
    
    # Field-level statistics (stored as JSON)
    field_stats = db.Column(db.JSON, default={})  # {field_id: {answered: count, skipped: count, avg_time: seconds}}
    
    # Page/Section statistics
    section_completion_rates = db.Column(db.JSON, default={})  # {section_id: completion_percentage}
    
    # Response rate
    view_count = db.Column(db.Integer, default=0)
    response_rate = db.Column(db.Float, default=0.0)  # percentage
    
    # Time statistics
    avg_completion_time = db.Column(db.Integer)  # in seconds
    median_completion_time = db.Column(db.Integer)
    
    # Dropout analysis
    avg_dropout_field_id = db.Column(db.Integer, db.ForeignKey('form_field.id'))  # Field where most users drop off
    
    last_updated = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    form = db.relationship('FeedbackForm', backref='analytics', uselist=False)
    dropout_field = db.relationship('FormField')


class FormCollaborator(db.Model):
    """Allow multiple users to collaborate on form creation and viewing responses"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Permission level
    role = db.Column(db.String(50), default='viewer')  # 'owner', 'editor', 'viewer', 'commenter'
    
    can_edit = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    can_view_responses = db.Column(db.Boolean, default=True)
    can_collect_responses = db.Column(db.Boolean, default=True)
    can_export_responses = db.Column(db.Boolean, default=False)
    can_share = db.Column(db.Boolean, default=False)
    
    added_at = db.Column(db.DateTime, default=get_ist_now)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    db.UniqueConstraint('form_id', 'user_id', name='unique_form_collaborator')
    
    form = db.relationship('FeedbackForm', backref='collaborators')
    user = db.relationship('User', foreign_keys=[user_id], backref='form_collaborations')
    added_by_user = db.relationship('User', foreign_keys=[added_by])


class FormSmtpSettings(db.Model):
    """
    Per-form SMTP configuration so a form owner can send their own
    "new response" notification emails through their own mail account
    (Gmail, Outlook, custom domain, etc.) instead of the platform's shared
    backend mailbox. Only used for the form-specific response-notification
    path (see app/feedback/routes.py:_send_email_notifications) — the
    submitter confirmation email and the platform admin notification are
    unaffected and keep using the backend mailer.

    The password is stored encrypted at rest via app/settings/crypto.py
    (same Fernet/SECRET_KEY-derived scheme already used for other sensitive
    app settings) and is NEVER returned by any route/API - only
    get_masked_email()/is_configured() flags are exposed to the frontend.
    """
    __tablename__ = 'form_smtp_settings'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, unique=True, index=True)

    is_enabled = db.Column(db.Boolean, default=False)  # user can save creds but keep it off

    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer, default=587)
    encryption = db.Column(db.String(10), default='tls')  # 'tls', 'ssl', 'none'
    smtp_email = db.Column(db.String(255))      # login / "From" address
    sender_name = db.Column(db.String(150))     # friendly display name for "From"
    smtp_password_encrypted = db.Column(db.Text)  # encrypted app password - never sent to client

    is_verified = db.Column(db.Boolean, default=False)   # last Test Connection succeeded
    last_test_status = db.Column(db.String(20))            # 'success' | 'failed'
    last_test_message = db.Column(db.String(255))
    last_tested_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

    form = db.relationship('FeedbackForm', backref=db.backref('smtp_settings', uselist=False))

    def set_password(self, raw_password):
        """Encrypt and store a new app password. Pass '' / None to clear it."""
        from app.settings.crypto import encrypt
        self.smtp_password_encrypted = encrypt(raw_password) if raw_password else None
        # Any credential change invalidates the last verification result.
        self.is_verified = False
        self.last_test_status = None
        self.last_test_message = None
        self.last_tested_at = None

    def get_password(self):
        """Decrypt and return the raw app password for sending mail. Never expose this value to the client."""
        if not self.smtp_password_encrypted:
            return None
        from app.settings.crypto import decrypt
        return decrypt(self.smtp_password_encrypted)

    def is_configured(self):
        return bool(self.smtp_host and self.smtp_port and self.smtp_email and self.smtp_password_encrypted)

    def get_masked_email(self):
        """'jane.doe@gmail.com' -> 'ja***@gmail.com' - safe to show in the UI."""
        if not self.smtp_email or '@' not in self.smtp_email:
            return ''
        local, _, domain = self.smtp_email.partition('@')
        visible = local[:2] if len(local) > 2 else local[:1]
        return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


class ResponseReply(db.Model):
    """
    Reply history for the *Self SMTP* form-owner reply feature.

    Deliberately separate from FeedbackReply (which backs the Admin
    reply-to-feedback workflow in app/admin/routes.py and always sends via
    the platform's backend mailbox). This table only ever records replies
    sent through a form owner's own SMTP credentials
    (see app/reply_email_service.py) and must never be read or written by
    the Admin email pipeline.
    """
    __tablename__ = 'response_reply'

    id = db.Column(db.Integer, primary_key=True)
    form_response_id = db.Column(db.Integer, db.ForeignKey('form_response.id'), nullable=False, index=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)

    recipient_email = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    reply_text = db.Column(db.Text, nullable=False)  # raw text the owner typed (fills {{admin_reply}})

    # Email threading (RFC 5322) so the reply lands in the same Gmail/Outlook thread
    message_id = db.Column(db.String(255))
    in_reply_to = db.Column(db.String(255))
    references = db.Column(db.String(1000))

    delivery_status = db.Column(db.String(20), default='pending')  # 'sent' | 'failed'
    error_message = db.Column(db.String(500))

    sent_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sent_at = db.Column(db.DateTime, default=get_ist_now, index=True)

    form_response = db.relationship(
        'FormResponse',
        backref=db.backref(
            'owner_replies', lazy='dynamic',
            order_by='ResponseReply.sent_at.desc(), ResponseReply.id.desc()',
            cascade='all, delete-orphan'
        )
    )
    form = db.relationship('FeedbackForm')
    sender = db.relationship('User', foreign_keys=[sent_by])


class FormNotification(db.Model):
    """Send notifications to form creators when responses are submitted"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Notification settings
    notify_on_each_response = db.Column(db.Boolean, default=True)
    notify_daily_digest = db.Column(db.Boolean, default=False)
    notify_weekly_digest = db.Column(db.Boolean, default=False)
    notification_email = db.Column(db.String(120), nullable=False)

    # Notification triggers
    notify_on_completion = db.Column(db.Boolean, default=True)
    notify_on_draft = db.Column(db.Boolean, default=False)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

    form = db.relationship('FeedbackForm', backref='notifications')
    user = db.relationship('User', backref='form_notifications')

    # --- compatibility aliases ---
    # app/form_persistence.py exports notifications using `email` and
    # `notification_type` / `notify_on_submission` names; keep them as
    # thin aliases over the real columns above so both call sites work
    # without maintaining two schemas.
    @property
    def email(self):
        return self.notification_email

    @email.setter
    def email(self, value):
        self.notification_email = value

    @property
    def notification_type(self):
        return 'email'

    @property
    def notify_on_submission(self):
        return self.notify_on_each_response

    @notify_on_submission.setter
    def notify_on_submission(self, value):
        self.notify_on_each_response = value


class LoginAttempt(db.Model):
    """Track login/registration attempts for rate limiting"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)  # IPv6 support
    success = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=get_ist_now, index=True)
    user_agent = db.Column(db.String(255))
    
    user = db.relationship('User', backref='login_attempts')
    
    def __repr__(self):
        status = 'success' if self.success else 'failed'
        return f'<LoginAttempt {self.ip_address} {status} at {self.timestamp}>'

class ContactMessage(db.Model):
    """Store contact form submissions"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(20))
    country = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    district = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(50), nullable=False)  # 'blocked_account', 'feature_request', 'bug_report', 'other'
    message = db.Column(db.Text, nullable=False)
    has_attachments = db.Column(db.Boolean, default=False)  # Whether files were uploaded
    attachments_data = db.Column(db.Text)  # JSON string storing file metadata: [{"filename": "...", "path": "...", "size": ...}]
    status = db.Column(db.String(20), default='new')  # 'new', 'replied', 'resolved', 'closed'
    admin_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Feature 4: Support tracking fields
    subject = db.Column(db.String(100))  # Brief subject line
    priority = db.Column(db.String(20), default='normal')  # 'normal', 'high', 'urgent'
    contact_method = db.Column(db.String(20), default='email')  # 'email', 'sms'
    
    # Feature 6: Submission tracking fields
    reference_id = db.Column(db.String(50), unique=True, index=True)  # Unique ticket reference
    ticket_id = db.Column(db.String(50), index=True, nullable=True)  # Link to generated ticket
    
    user = db.relationship('User', backref='contact_messages')
    
    def __repr__(self):
        return f'<ContactMessage {self.reference_id} - {self.email}>'


class EmailTemplate(db.Model):
    """Store custom email templates for broadcasts and system notifications"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    template_type = db.Column(db.String(50), nullable=False, default='broadcast')  # 'broadcast', 'profile_update_reminder', 'feedback_confirmation', etc.
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    creator = db.relationship('User', backref='email_templates')
    broadcasts = db.relationship('Broadcast', backref='email_template', lazy=True)
    
    def __repr__(self):
        return f'<EmailTemplate {self.name}>'


class Broadcast(db.Model):
    """Store broadcast campaigns"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    email_template_id = db.Column(db.Integer, db.ForeignKey('email_template.id'), nullable=False)
    broadcast_type = db.Column(db.String(50), nullable=False)  # 'all_users', 'active_users', 'custom'
    target_users = db.Column(db.Text)  # JSON array of user IDs for custom type
    status = db.Column(db.String(20), default='draft')  # 'draft', 'scheduled', 'sending', 'sent', 'failed'
    scheduled_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    total_recipients = db.Column(db.Integer, default=0)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    creator = db.relationship('User', backref='broadcasts')
    recipients = db.relationship('BroadcastRecipient', backref='broadcast', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Broadcast {self.title}>'


class BroadcastRecipient(db.Model):
    """Track broadcast delivery status for each recipient"""
    id = db.Column(db.Integer, primary_key=True)
    broadcast_id = db.Column(db.Integer, db.ForeignKey('broadcast.id'), nullable=False, index=True)
    recipient_email = db.Column(db.String(120), nullable=False, index=True)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'sent', 'failed', 'bounced'
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    
    def __repr__(self):
        return f'<BroadcastRecipient {self.recipient_email} - {self.status}>'


class ProfileCompletionTracker(db.Model):
    """Track profile completion percentage for each user"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    
    # Completion fields
    has_first_name = db.Column(db.Boolean, default=False)
    has_last_name = db.Column(db.Boolean, default=False)
    has_phone = db.Column(db.Boolean, default=False)
    has_bio = db.Column(db.Boolean, default=False)
    has_profile_picture = db.Column(db.Boolean, default=False)
    has_device_selection = db.Column(db.Boolean, default=False)
    has_country = db.Column(db.Boolean, default=False)
    
    # Calculated completion percentage
    completion_percentage = db.Column(db.Integer, default=0)
    
    # Last update
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    user = db.relationship('User', backref='profile_tracker')
    
    def calculate_completion(self):
        """Calculate profile completion percentage"""
        total_fields = 7
        completed = sum([
            self.has_first_name,
            self.has_last_name,
            self.has_phone,
            self.has_bio,
            self.has_profile_picture,
            self.has_device_selection,
            self.has_country
        ])
        self.completion_percentage = int((completed / total_fields) * 100)
        return self.completion_percentage


class ProfileReminderEmail(db.Model):
    """Track profile completion reminder emails sent to users"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Email metadata
    sent_at = db.Column(db.DateTime, default=get_ist_now)
    email_type = db.Column(db.String(50), default='daily')  # 'daily', 'weekly', 'one_time'
    
    # User's profile completion at time of email
    completion_percentage_at_send = db.Column(db.Integer)
    
    # Email engagement
    was_opened = db.Column(db.Boolean, default=False)
    opened_at = db.Column(db.DateTime)
    was_clicked = db.Column(db.Boolean, default=False)
    clicked_at = db.Column(db.DateTime)
    
    # Status
    status = db.Column(db.String(20), default='sent')  # 'pending', 'sent', 'failed', 'bounced'
    error_message = db.Column(db.Text)
    
    user = db.relationship('User', backref='reminder_emails')
    
    def __repr__(self):
        return f'<ProfileReminderEmail user_id={self.user_id} sent={self.sent_at}>'


class FormCreatorRequest(db.Model):
    """Model for Form Creator access requests from users"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Request details - pre-filled with user info
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    organization = db.Column(db.String(255))
    
    # Location information
    country = db.Column(db.String(100))
    state = db.Column(db.String(100))
    district = db.Column(db.String(100))
    
    # Device information
    device_type = db.Column(db.String(50))  # e.g., 'mobile', 'desktop', 'tablet'
    device_os = db.Column(db.String(100))   # e.g., 'Windows', 'macOS', 'Android', 'iOS'
    
    # Purpose and details
    purpose = db.Column(db.Text, nullable=False)  # Purpose for form creation
    use_case = db.Column(db.Text)  # Specific use case details
    description = db.Column(db.Text)  # Additional description
    industry = db.Column(db.String(100))  # Industry/sector
    expected_volume = db.Column(db.String(100))  # Expected monthly form submissions
    
    # Admin review
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'approved', 'rejected'
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)
    
    # Rejection details (only if rejected)
    rejection_reason = db.Column(db.Text)
    rejection_suggestions = db.Column(db.Text)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='form_creator_requests')
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_id], backref='reviewed_form_creator_requests')
    
    def __repr__(self):
        return f'<FormCreatorRequest user_id={self.user_id} status={self.status}>'


class EmailLog(db.Model):
    """Track email delivery: success, failures, and retries"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    email_address = db.Column(db.String(120), nullable=False, index=True)
    email_type = db.Column(db.String(50), nullable=False, index=True)  # 'welcome', 'oauth_welcome', 'verification', etc.
    subject = db.Column(db.String(255))
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'sent', 'failed', 'bounced'
    error_message = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    max_retries = db.Column(db.Integer, default=3)
    sent_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # OAuth tracking
    oauth_provider = db.Column(db.String(50))  # 'google', 'github', etc.
    
    def __repr__(self):
        return f'<EmailLog type={self.email_type} status={self.status} email={self.email_address}>'


class CaptchaLog(db.Model):
    """Track reCAPTCHA verification attempts for security and abuse monitoring"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)  # Support IPv4 and IPv6
    form_name = db.Column(db.String(100), nullable=False)  # 'login', 'register', 'contact', etc.
    captcha_token = db.Column(db.String(500))
    success = db.Column(db.Boolean, default=False, index=True)
    score = db.Column(db.Float)  # reCAPTCHA v3 score (0.0-1.0), null for v2
    action = db.Column(db.String(50))  # The action that triggered the challenge
    challenge_triggered = db.Column(db.Boolean, default=False, index=True)  # Did user see image challenge?
    user_agent = db.Column(db.String(255))  # Browser/device info
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    
    def __repr__(self):
        return f'<CaptchaLog form={self.form_name} ip={self.ip_address} success={self.success}>'


class AdminSecuritySetting(db.Model):
    """Global security settings for reCAPTCHA and other security features"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Global CAPTCHA enablement
    captcha_enabled = db.Column(db.Boolean, default=True, index=True)
    
    # Default CAPTCHA version: 'v2', 'v3', or 'none'
    captcha_default_version = db.Column(db.String(20), default='v2', index=True)
    
    # reCAPTCHA v2 settings
    recaptcha_v2_enabled = db.Column(db.Boolean, default=True)
    recaptcha_v2_site_key = db.Column(db.String(500))
    recaptcha_v2_secret_key = db.Column(db.String(500))
    
    # reCAPTCHA v3 settings
    recaptcha_v3_enabled = db.Column(db.Boolean, default=True)
    recaptcha_v3_site_key = db.Column(db.String(500))
    recaptcha_v3_secret_key = db.Column(db.String(500))
    recaptcha_v3_threshold = db.Column(db.Float, default=0.5)  # 0.0-1.0 score threshold
    
    # Abuse detection thresholds
    failed_attempts_threshold = db.Column(db.Integer, default=5)
    failed_rate_threshold = db.Column(db.Integer, default=50)  # Percentage
    
    # Security modes
    aggressive_mode = db.Column(db.Boolean, default=False)  # Stricter CAPTCHA enforcement
    
    # Audit trail
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    def __repr__(self):
        return f'<AdminSecuritySetting captcha_version={self.captcha_default_version}>'


class FormCaptchaSetting(db.Model):
    """Per-form CAPTCHA configuration (overrides global settings)"""
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, unique=True, index=True)
    
    # CAPTCHA settings for this form
    # 'inherit' = use global setting, 'v2', 'v3', 'none'
    captcha_version = db.Column(db.String(20), default='inherit', index=True)
    
    # Override global enablement for this form only
    captcha_enabled = db.Column(db.Boolean, default=None, nullable=True)  # None = inherit
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Relationship
    form = db.relationship('FeedbackForm', backref='captcha_setting')
    
    def get_effective_version(self, global_setting):
        """Get the effective CAPTCHA version (respecting inheritance)"""
        if self.captcha_version == 'inherit':
            return global_setting
        return self.captcha_version
    
    def is_enabled(self, global_enabled):
        """Check if CAPTCHA is enabled (respecting inheritance)"""
        if self.captcha_enabled is None:
            return global_enabled
        return self.captcha_enabled
    
    def __repr__(self):
        return f'<FormCaptchaSetting form_id={self.form_id} version={self.captcha_version}>'


class Ticket(db.Model):
    """
    Ticket model for tracking form submissions with unique ticket IDs.
    Allows users to look up their submissions and track status.
    """
    __tablename__ = 'ticket'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.String(15), unique=True, nullable=False, index=True)  # 5-10 alphanumeric chars
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)  # For authenticated users
    respondent_email = db.Column(db.String(255), nullable=True, index=True)  # For non-authenticated submissions
    respondent_name = db.Column(db.String(255), nullable=True)  # Store respondent name for reference
    
    status = db.Column(db.String(50), default='new', index=True)  # new, in_progress, resolved, closed
    status_notes = db.Column(db.Text, nullable=True)  # Admin notes about status
    
    last_updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Admin who last updated
    
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now, index=True)
    
    # Relationships
    form = db.relationship('FeedbackForm', backref='tickets', foreign_keys=[form_id])
    user = db.relationship('User', backref='tickets', foreign_keys=[user_id])
    last_updated_by = db.relationship('User', foreign_keys=[last_updated_by_id])
    session = db.relationship('TicketSession', backref='ticket', uselist=False, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Ticket ticket_id={self.ticket_id} form_id={self.form_id} status={self.status}>'


class TicketSession(db.Model):
    """
    Session data associated with a ticket submission.
    Stores device info, IP, session details for security and tracking.
    """
    __tablename__ = 'ticket_session'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False, unique=True, index=True)
    
    # Device and session information
    device_type = db.Column(db.String(50), nullable=True)  # desktop, mobile, tablet
    browser_name = db.Column(db.String(100), nullable=True)
    browser_version = db.Column(db.String(50), nullable=True)
    os_name = db.Column(db.String(100), nullable=True)
    os_version = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    
    ip_address = db.Column(db.String(45), nullable=True, index=True)  # IPv4 or IPv6
    country = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    
    # Session metadata
    session_id = db.Column(db.String(255), nullable=True, unique=True)
    referrer = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=get_ist_now)
    
    def __repr__(self):
        return f'<TicketSession ticket_id={self.ticket_id} device={self.device_type}>'


class UserNotification(db.Model):
    """
    User notification model for in-app notifications.
    Supports dual delivery (stored in DB + sent via email).
    Supports multiple action buttons.
    """
    __tablename__ = 'user_notification'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    
    # Notification content
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default='general', index=True)  # general, ticket, status_update, profile, system
    priority = db.Column(db.String(20), default='medium')  # low, medium, high, critical
    
    # Action link (optional - backward compatibility)
    action_url = db.Column(db.String(500), nullable=True)  # Link to ticket detail, profile, etc.
    action_text = db.Column(db.String(100), nullable=True)  # "View Ticket", "Complete Profile", etc.
    
    # Multiple buttons support (JSON format)
    buttons = db.Column(db.Text, nullable=True)  # JSON array of {label, url, style} objects
    
    # Status tracking
    is_read = db.Column(db.Boolean, default=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    
    # Email tracking
    email_sent = db.Column(db.Boolean, default=False)
    email_sent_at = db.Column(db.DateTime, nullable=True)
    email_failed = db.Column(db.Boolean, default=False)
    email_error = db.Column(db.Text, nullable=True)  # Store error message if email fails
    
    # Related records (for quick lookup without joins)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    
    # Relationships
    user = db.relationship('User', backref='notifications', foreign_keys=[user_id])
    ticket = db.relationship('Ticket', foreign_keys=[ticket_id])
    
    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        self.read_at = get_ist_now()
        db.session.commit()
    
    def get_buttons(self):
        """Parse buttons JSON and return as list"""
        if not self.buttons:
            return []
        try:
            import json
            return json.loads(self.buttons)
        except (json.JSONDecodeError, ValueError):
            return []
    
    def set_buttons(self, buttons_list):
        """Set buttons from list of dicts"""
        try:
            import json
            self.buttons = json.dumps(buttons_list) if buttons_list else None
        except (TypeError, ValueError):
            self.buttons = None
    
    def __repr__(self):
        return f'<UserNotification user_id={self.user_id} type={self.notification_type} read={self.is_read}>'


class PersonalDocument(db.Model):
    """Model for user personal documents (Google Drive-like functionality)."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('document_folder.id'), nullable=True)  # Folder organization
    
    # File information
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, index=True)
    file_size_bytes = db.Column(db.Integer, nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    file_extension = db.Column(db.String(10), nullable=False, index=True)
    
    # Storage information
    storage_path = db.Column(db.String(500), nullable=False)
    cloud_storage_path = db.Column(db.String(500))  # Path in internal cloud storage
    cloud_storage_id = db.Column(db.String(255))  # ID in cloud storage system
    is_cloud_stored = db.Column(db.Boolean, default=True)  # Whether stored in cloud
    
    # File metadata
    file_hash = db.Column(db.String(64))  # SHA-256 hash for integrity verification
    cloud_metadata = db.Column(db.Text)  # JSON metadata from cloud storage
    
    # Document information
    document_name = db.Column(db.String(255), nullable=False, index=True)  # User-friendly name
    document_category = db.Column(db.String(50), index=True)  # 'pdf', 'image', 'video', 'audio', 'document', 'archive', 'code', 'other'
    description = db.Column(db.Text)  # User description
    tags = db.Column(db.Text)  # Comma-separated tags
    
    # Timestamps
    uploaded_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    last_accessed_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Security & Privacy
    is_public = db.Column(db.Boolean, default=False)  # Allow public sharing
    shared_with = db.Column(db.Text)  # JSON array of user IDs with access
    is_encrypted = db.Column(db.Boolean, default=True)  # Whether file is encrypted
    encryption_key_id = db.Column(db.String(100))  # ID of encryption key used
    
    # Virus scanning
    scanned_for_viruses = db.Column(db.Boolean, default=False)
    virus_scan_result = db.Column(db.String(20))  # 'clean', 'infected', 'pending', 'error'
    virus_scan_timestamp = db.Column(db.DateTime)
    
    # Admin oversight
    is_flagged_by_admin = db.Column(db.Boolean, default=False)
    flagged_reason = db.Column(db.Text)
    flagged_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    flagged_at = db.Column(db.DateTime)
    
    # Access tracking
    download_count = db.Column(db.Integer, default=0)
    view_count = db.Column(db.Integer, default=0)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='personal_documents')
    admin_flag = db.relationship('User', foreign_keys=[flagged_by])
    
    def get_file_type_icon(self):
        """Return emoji icon based on file type."""
        icon_map = {
            'pdf': '📄', 'doc': '📄', 'docx': '📄', 'txt': '📄', 'rtf': '📄', 'odt': '📄',
            'jpg': '[IMG]️', 'jpeg': '[IMG]️', 'png': '[IMG]️', 'gif': '[IMG]️', 'webp': '[IMG]️', 'svg': '[IMG]️', 'bmp': '[IMG]️',
            'mp4': '[VIDEO]', 'avi': '[VIDEO]', 'mov': '[VIDEO]', 'mkv': '[VIDEO]', 'flv': '[VIDEO]', 'wmv': '[VIDEO]', 'webm': '[VIDEO]',
            'mp3': '[AUDIO]', 'wav': '[AUDIO]', 'flac': '[AUDIO]', 'aac': '[AUDIO]', 'm4a': '[AUDIO]', 'ogg': '[AUDIO]',
            'zip': '[PKG]', 'rar': '[PKG]', '7z': '[PKG]', 'tar': '[PKG]', 'gz': '[PKG]',
            'xls': '📊', 'xlsx': '📊', 'csv': '📊', 'ods': '📊',
            'ppt': '📊', 'pptx': '📊', 'odp': '📊',
            'py': '[PC]', 'js': '[PC]', 'html': '[PC]', 'css': '[PC]', 'java': '[PC]', 'cpp': '[PC]', 'c': '[PC]',
        }
        ext = self.file_extension.lower()
        return icon_map.get(ext, '📋')
    
    def get_file_category(self):
        """Determine file category from extension."""
        ext = self.file_extension.lower()
        
        image_exts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'tiff']
        doc_exts = ['pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'pages']
        video_exts = ['mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv', 'webm', 'm4v']
        audio_exts = ['mp3', 'wav', 'flac', 'aac', 'm4a', 'wma', 'ogg', 'aiff']
        archive_exts = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2']
        spreadsheet_exts = ['xls', 'xlsx', 'csv', 'ods', 'numbers']
        presentation_exts = ['ppt', 'pptx', 'odp', 'keynote']
        code_exts = ['py', 'js', 'html', 'css', 'java', 'cpp', 'c', 'json', 'xml', 'sql']
        
        if ext in image_exts:
            return 'Image'
        elif ext in doc_exts:
            return 'Document'
        elif ext in video_exts:
            return 'Video'
        elif ext in audio_exts:
            return 'Audio'
        elif ext in archive_exts:
            return 'Archive'
        elif ext in spreadsheet_exts:
            return 'Spreadsheet'
        elif ext in presentation_exts:
            return 'Presentation'
        elif ext in code_exts:
            return 'Code'
        else:
            return 'Other'
    
    def get_shared_with_ids(self):
        """Get list of user IDs with access to this document."""
        if not self.shared_with:
            return []
        try:
            import json
            return json.loads(self.shared_with)
        except:
            return []
    
    def set_shared_with_ids(self, user_ids):
        """Set list of user IDs with access to this document."""
        import json
        self.shared_with = json.dumps(user_ids) if user_ids else None
    
    def add_shared_user(self, user_id):
        """Add a user to the shared list."""
        ids = self.get_shared_with_ids()
        if user_id not in ids:
            ids.append(user_id)
            self.set_shared_with_ids(ids)
            return True
        return False
    
    def remove_shared_user(self, user_id):
        """Remove a user from the shared list."""
        ids = self.get_shared_with_ids()
        if user_id in ids:
            ids.remove(user_id)
            self.set_shared_with_ids(ids)
            return True
        return False
    
    def record_access(self):
        """Record document access."""
        self.view_count = (self.view_count or 0) + 1
        self.last_accessed_at = get_ist_now()
    
    def can_user_access(self, user_id):
        """Check if user can access this document."""
        if self.user_id == user_id:
            return True
        if self.is_public:
            return True
        return user_id in self.get_shared_with_ids()
    
    @property
    def size_readable(self):
        """Return human-readable file size."""
        size = self.file_size_bytes
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def __repr__(self):
        return f'<PersonalDocument user_id={self.user_id} filename={self.original_filename}>'


class DocumentFolder(db.Model):
    """Folder model for organizing documents into folders (like Google Drive)."""
    __tablename__ = 'document_folder'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    parent_folder_id = db.Column(db.Integer, db.ForeignKey('document_folder.id'), nullable=True)
    
    # Folder information
    folder_name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(20), default='#3B82F6')  # Blue by default
    icon = db.Column(db.String(10), default='📁')  # Default folder emoji
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    
    # Relationships
    user = db.relationship('User', backref='document_folders')
    parent_folder = db.relationship('DocumentFolder', remote_side=[id], backref='subfolders')
    documents = db.relationship('PersonalDocument', backref='folder', lazy=True, 
                              foreign_keys='PersonalDocument.folder_id')
    
    def get_full_path(self):
        """Get the full folder path (parent/subfolder structure)."""
        path = [self.folder_name]
        current = self.parent_folder
        while current:
            path.insert(0, current.folder_name)
            current = current.parent_folder
        return ' / '.join(path)
    
    def get_document_count(self):
        """Get count of documents directly in this folder."""
        return PersonalDocument.query.filter_by(folder_id=self.id).count()
    
    def get_subfolder_count(self):
        """Get count of subfolders."""
        return DocumentFolder.query.filter_by(parent_folder_id=self.id).count()
    
    def to_dict(self):
        """Convert to dictionary for JSON response."""
        return {
            'id': self.id,
            'name': self.folder_name,
            'description': self.description,
            'color': self.color,
            'icon': self.icon,
            'parent_id': self.parent_folder_id,
            'full_path': self.get_full_path(),
            'document_count': self.get_document_count(),
            'subfolder_count': self.get_subfolder_count(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    def __repr__(self):
        return f'<DocumentFolder user_id={self.user_id} name={self.folder_name}>'


class FormSlugAlias(db.Model):
    """
    Track old form slugs to redirect users to new slugs when form slug changes.
    Enables seamless migration without breaking existing links.
    """
    __tablename__ = 'form_slug_alias'
    
    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('feedback_form.id'), nullable=False, index=True)
    old_slug = db.Column(db.String(200), nullable=False, unique=True, index=True)
    new_slug = db.Column(db.String(200), nullable=False)
    
    # Tracking
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    is_active = db.Column(db.Boolean, default=True, index=True)
    
    # Statistics
    redirect_count = db.Column(db.Integer, default=0)  # Track how many redirects happened
    last_redirect_at = db.Column(db.DateTime)  # Last time this redirect was used
    
    # Relationships
    form = db.relationship('FeedbackForm', backref='slug_aliases', lazy=True,
                          foreign_keys='FormSlugAlias.form_id')
    
    def __repr__(self):
        return f'<FormSlugAlias old={self.old_slug} → new={self.new_slug}>'
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'old_slug': self.old_slug,
            'new_slug': self.new_slug,
            'is_active': self.is_active,
            'redirect_count': self.redirect_count,
            'last_redirect': self.last_redirect_at.isoformat() if self.last_redirect_at else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class UserPasskey(db.Model):
    """Store user passkeys for WebAuthn/FIDO2 authentication"""
    __tablename__ = 'user_passkey'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    credential_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    public_key = db.Column(db.Text, nullable=False)
    transports = db.Column(db.Text, default='[]')  # JSON array of transports (usb, ble, nfc, internal)
    device_name = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=get_ist_now)
    last_used_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True, index=True)
    sign_count = db.Column(db.Integer, default=0)  # Counter for clone detection
    aaguid = db.Column(db.String(36))  # Authenticator AAGUID
    
    user = db.relationship('User', backref=db.backref('passkeys', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<UserPasskey user={self.user_id} device={self.device_name}>'


class UserSession(db.Model):
    """
    Tracks individual authenticated sessions (one row per login) so users can
    see "Active sessions" / "Connected devices" and revoke them individually,
    independent of Flask's signed session cookie.
    """
    __tablename__ = 'user_session'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    session_token = db.Column(db.String(128), unique=True, nullable=False, index=True)

    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    browser = db.Column(db.String(100))
    os = db.Column(db.String(100))
    device_type = db.Column(db.String(50))
    location = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    last_active_at = db.Column(db.DateTime, default=get_ist_now)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)

    user = db.relationship('User', backref=db.backref('sessions', lazy='dynamic', cascade='all, delete-orphan'))

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def device_label(self):
        browser = self.browser or 'Unknown browser'
        os_name = self.os or 'Unknown OS'
        return f"{browser} on {os_name}"

    def revoke(self):
        self.revoked_at = get_ist_now()

    def __repr__(self):
        return f'<UserSession user={self.user_id} active={self.is_active}>'


class UserPreference(db.Model):
    """Single row per user holding notifications, appearance, privacy and
    regional preferences (everything on the Settings page besides Profile
    fields, which live directly on User/UserProfile)."""
    __tablename__ = 'user_preference'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)

    # Notifications
    push_notifications = db.Column(db.Boolean, default=False)
    browser_notifications = db.Column(db.Boolean, default=False)
    marketing_emails = db.Column(db.Boolean, default=False)
    security_alerts = db.Column(db.Boolean, default=True)

    # Appearance
    theme = db.Column(db.String(20), default='system')
    accent_color = db.Column(db.String(20), default='purple')
    font_size = db.Column(db.String(20), default='medium')
    compact_mode = db.Column(db.Boolean, default=False)

    # Privacy
    profile_visibility = db.Column(db.String(20), default='private')
    data_sharing = db.Column(db.Boolean, default=False)

    # Regional / Preferences
    language = db.Column(db.String(10), default='en')
    timezone = db.Column(db.String(64), default='Asia/Kolkata')
    date_format = db.Column(db.String(20), default='DD/MM/YYYY')
    time_format = db.Column(db.String(10), default='24h')

    created_at = db.Column(db.DateTime, default=get_ist_now)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)

    user = db.relationship('User', backref=db.backref('preference', uselist=False, cascade='all, delete-orphan'))

    @classmethod
    def get_or_create(cls, user_id):
        pref = cls.query.filter_by(user_id=user_id).first()
        if not pref:
            pref = cls(user_id=user_id)
            db.session.add(pref)
            db.session.commit()
        return pref

    def to_dict(self):
        return {
            'notifications': {
                'push_notifications': self.push_notifications,
                'browser_notifications': self.browser_notifications,
                'marketing_emails': self.marketing_emails,
                'security_alerts': self.security_alerts,
            },
            'appearance': {
                'theme': self.theme,
                'accent_color': self.accent_color,
                'font_size': self.font_size,
                'compact_mode': self.compact_mode,
            },
            'privacy': {
                'profile_visibility': self.profile_visibility,
                'data_sharing': self.data_sharing,
            },
            'regional': {
                'language': self.language,
                'timezone': self.timezone,
                'date_format': self.date_format,
                'time_format': self.time_format,
            },
        }

    def __repr__(self):
        return f'<UserPreference user={self.user_id} theme={self.theme}>'


class BlockedDomain(db.Model):
    """Admin-managed email domain block list (registration + login enforcement).

    status='approved' domains are actively enforced everywhere is_temp_email()
    is used. status='pending' domains were auto-flagged by the heuristic
    detector in temp_mail_blocker.py and are NOT enforced until an admin
    approves them.
    """
    __tablename__ = 'blocked_domain'

    id = db.Column(db.Integer, primary_key=True)
    domain = db.Column(db.String(255), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='approved', index=True)  # pending | approved | rejected
    source = db.Column(db.String(20), nullable=False, default='manual')  # manual | auto_detected
    reason = db.Column(db.String(255))
    added_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    reviewed_at = db.Column(db.DateTime)

    added_by = db.relationship('User', foreign_keys=[added_by_admin_id])
    reviewed_by = db.relationship('User', foreign_keys=[reviewed_by_admin_id])

    def __repr__(self):
        return f'<BlockedDomain {self.domain} status={self.status}>'


class BlockedDomainRevocation(db.Model):
    """Revocation log written the moment a domain transitions to 'approved'.

    The before_request domain-check middleware reads this table to decide whether
    a currently-logged-in user's session must be force-expired.

    Design:
    - One row per domain.  If the same domain is approved -> rejected -> approved
      again, ``approved_at`` is updated in-place so stale rows don't accumulate.
    - Any authenticated session whose email domain appears here is immediately
      invalid — the domain is actively blocked right now.
    - Rows are removed when the domain is rejected or deleted, so un-blocking
      a domain instantly restores access for its users.
    """
    __tablename__ = 'blocked_domain_revocation'

    id                   = db.Column(db.Integer, primary_key=True)
    domain               = db.Column(db.String(255), unique=True, nullable=False, index=True)
    approved_at          = db.Column(db.DateTime, nullable=False, default=get_ist_now)
    approved_by_admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    approved_by = db.relationship('User', foreign_keys=[approved_by_admin_id])

    def __repr__(self):
        return f'<BlockedDomainRevocation {self.domain} at={self.approved_at}>'

    # ------------------------------------------------------------------
    # Class helpers called by admin routes and the middleware
    # ------------------------------------------------------------------

    @classmethod
    def upsert(cls, domain, admin_id=None):
        """Insert or refresh the revocation record for *domain*.

        Called immediately after a domain is approved so that the middleware
        begins force-logging-out affected users on their very next request.
        Safe to call multiple times (idempotent).
        """
        domain = domain.strip().lower()
        existing = cls.query.filter_by(domain=domain).first()
        if existing:
            existing.approved_at          = get_ist_now()
            existing.approved_by_admin_id = admin_id
        else:
            db.session.add(cls(domain=domain, approved_by_admin_id=admin_id))
        # Caller is responsible for db.session.commit() (already done in admin routes)

    @classmethod
    def remove(cls, domain):
        """Remove the revocation record when a domain is un-blocked
        (rejected or deleted), so previously-affected users can log in again.
        Caller is responsible for db.session.commit().
        """
        domain = domain.strip().lower()
        cls.query.filter_by(domain=domain).delete()

    @classmethod
    def is_revoked(cls, domain):
        """Return True if *domain* is currently in the active revocation set."""
        domain = domain.strip().lower()
        return db.session.query(
            cls.query.filter_by(domain=domain).exists()
        ).scalar()


class FormDraft(db.Model):
    """Auto-saved form draft for all form types"""
    __tablename__ = 'form_draft'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    form_id = db.Column(db.Integer, nullable=True)
    draft_key = db.Column(db.String(255), nullable=False, index=True)
    form_type = db.Column(db.String(50), nullable=False, index=True)
    session_id = db.Column(db.String(255), nullable=True)
    
    draft_data = db.Column(db.Text)
    field_values = db.Column(db.Text, default='{}')
    attachments = db.Column(db.Text, default='[]')
    
    created_at = db.Column(db.DateTime, default=get_ist_now, index=True)
    updated_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now)
    last_saved_at = db.Column(db.DateTime, default=get_ist_now, onupdate=get_ist_now, index=True)
    last_accessed_at = db.Column(db.DateTime, default=get_ist_now)
    last_autosave_at = db.Column(db.DateTime)
    
    expires_at = db.Column(db.DateTime, default=lambda: get_ist_now() + timedelta(days=30), index=True)
    
    is_active = db.Column(db.Boolean, default=True, index=True)
    is_submitted = db.Column(db.Boolean, default=False)
    is_completed = db.Column(db.Boolean, default=False)
    
    progress_percentage = db.Column(db.Integer, default=0)
    
    device_fingerprint = db.Column(db.String(255))
    user_agent = db.Column(db.String(500))
    ip_address = db.Column(db.String(45))
    
    user = db.relationship('User', backref=db.backref('form_drafts', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<FormDraft type={self.form_type} user={self.user_id}>'
    
    def to_dict(self):
        """Convert draft to dictionary"""
        import json
        draft_dict = self.draft_data or self.field_values or '{}'
        return {
            'id': self.id,
            'draft_key': self.draft_key,
            'form_type': self.form_type,
            'form_id': self.form_id,
            'draft_data': json.loads(draft_dict) if isinstance(draft_dict, str) else draft_dict,
            'created_at': self.created_at.isoformat(),
            'last_saved_at': self.last_saved_at.isoformat(),
            'last_accessed_at': self.last_accessed_at.isoformat(),
            'progress_percentage': self.progress_percentage,
        }
    
    @staticmethod
    def cleanup_expired_drafts():
        """Delete drafts that have expired"""
        try:
            expired_count = FormDraft.query.filter(
                FormDraft.expires_at < get_ist_now()
            ).delete()
            db.session.commit()
            return expired_count
        except Exception as e:
            db.session.rollback()
            return 0


class DraftVersion(db.Model):
    """Version history for form drafts"""
    __tablename__ = 'draft_version'
    
    id = db.Column(db.Integer, primary_key=True)
    draft_id = db.Column(db.Integer, db.ForeignKey('form_draft.id'), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False)
    field_values = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=get_ist_now)
    created_by = db.Column(db.String(50))
    change_summary = db.Column(db.String(255))
    
    draft = db.relationship('FormDraft', backref=db.backref('versions', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<DraftVersion draft={self.draft_id} v{self.version_number}>'