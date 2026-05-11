from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
from functools import wraps
import os
import enum
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-change-this')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////home/trading/scalping-app/scalping.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER')

BASE_URL = os.getenv('BASE_URL', 'https://scalping.adaptiverealtimetrading.co.uk')

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
mail = Mail(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])


class Role(enum.Enum):
    admin = 'admin'
    trader = 'trader'
    monitor = 'monitor'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(Role), default=Role.monitor, nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    is_verified = db.Column(db.Boolean, default=False)
    is_suspended = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.is_verified and self.is_approved and not self.is_suspended

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != Role.admin:
            return redirect(url_for('landing'))
        return f(*args, **kwargs)
    return decorated


def make_token(data, salt):
    return serializer.dumps(data, salt=salt)


def read_token(token, salt, max_age=86400):
    try:
        return serializer.loads(token, salt=salt, max_age=max_age)
    except Exception:
        return None


# Routes

@app.route('/', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('landing'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if user.is_suspended:
                error = 'suspended'
            elif not user.is_approved:
                error = 'pending_approval'
            elif not user.is_verified:
                error = 'pending_verification'
            else:
                login_user(user)
                return redirect(url_for('landing'))
        else:
            error = 'invalid'
    return render_template('login.html', error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('landing'))
    errors = []
    form = {}
    if request.method == 'POST':
        form['username'] = request.form.get('username', '').strip()
        form['email'] = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        if not form['username']:
            errors.append('Username is required.')
        if not form['email']:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if not confirm:
            errors.append('Please confirm your password.')
        if password and confirm and password != confirm:
            errors.append('Passwords do not match.')
        if form['username'] and User.query.filter_by(username=form['username']).first():
            errors.append('Username already taken.')
        if form['email'] and User.query.filter_by(email=form['email']).first():
            errors.append('Email already registered.')

        if not errors:
            first_user = User.query.count() == 0
            user = User(username=form['username'], email=form['email'])
            user.set_password(password)
            if first_user:
                user.role = Role.admin
                user.is_approved = True
                user.is_verified = True
            else:
                user.role = Role.monitor
            db.session.add(user)
            db.session.commit()

            if first_user:
                return render_template('register.html', first_admin=True)

            approve_tok = make_token({'uid': user.id, 'action': 'approve'}, 'admin-action')
            deny_tok = make_token({'uid': user.id, 'action': 'deny'}, 'admin-action')
            for admin in User.query.filter_by(role=Role.admin).all():
                _send_approval_request(admin.email, user.username, user.email,
                                       approve_tok, deny_tok)
            return render_template('register.html', pending=True)

    return render_template('register.html', errors=errors, form=form)


@app.route('/admin/action/<token>')
def admin_action(token):
    data = read_token(token, 'admin-action')
    if not data:
        return render_template('message.html', title='Link Expired',
                               message='This link is invalid or has expired.')
    user = db.session.get(User, data.get('uid'))
    if not user:
        return render_template('message.html', title='Not Found',
                               message='User not found.')
    if data.get('action') == 'approve':
        if user.is_approved:
            return render_template('message.html', title='Already Approved',
                                   message=f'{user.username} has already been approved.')
        user.is_approved = True
        db.session.commit()
        vtok = make_token({'uid': user.id}, 'email-verify')
        _send_verification(user.email, user.username, vtok)
        return render_template('message.html', title='User Approved',
                               message=f'{user.username} approved. Verification email sent.')
    elif data.get('action') == 'deny':
        name = user.username
        db.session.delete(user)
        db.session.commit()
        return render_template('message.html', title='Registration Denied',
                               message=f'Registration for {name} has been denied.')
    return render_template('message.html', title='Unknown Action',
                           message='Unknown action.')


@app.route('/verify/<token>')
def verify_email(token):
    data = read_token(token, 'email-verify')
    if not data:
        return render_template('message.html', title='Link Expired',
                               message='This verification link is invalid or has expired.')
    user = db.session.get(User, data.get('uid'))
    if not user:
        return render_template('message.html', title='Not Found',
                               message='User not found.')
    user.is_verified = True
    db.session.commit()
    return render_template('message.html', title='Email Verified',
                           message='Your email has been verified. You can now log in.',
                           show_login=True)


@app.route('/landing')
@login_required
def landing():
    return render_template('landing.html')


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    ctx = {}
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'change_email':
            new_email = request.form.get('new_email', '').strip()
            if not new_email:
                ctx['email_error'] = 'Email is required.'
            elif User.query.filter(User.email == new_email,
                                   User.id != current_user.id).first():
                ctx['email_error'] = 'That email is already in use.'
            else:
                current_user.email = new_email
                db.session.commit()
                ctx['email_success'] = 'Email updated successfully.'
        elif action == 'change_password':
            cur = request.form.get('current_password', '')
            new = request.form.get('new_password', '')
            con = request.form.get('confirm_password', '')
            if not current_user.check_password(cur):
                ctx['pw_error'] = 'Current password is incorrect.'
            elif not new:
                ctx['pw_error'] = 'New password is required.'
            elif new != con:
                ctx['pw_error'] = 'Passwords do not match.'
            else:
                current_user.set_password(new)
                db.session.commit()
                ctx['pw_success'] = 'Password updated successfully.'
    return render_template('profile.html', **ctx)


@app.route('/forgot-username', methods=['GET', 'POST'])
def forgot_username():
    sent = False
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            _send_username_reminder(user.email, user.username)
        sent = True
    return render_template('forgot_username.html', sent=sent)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    sent = False
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        user = User.query.filter_by(email=email).first()
        if user:
            # Suspend the account until the reset link is used
            user.is_suspended = True
            db.session.commit()
            tok = make_token({'uid': user.id}, 'pw-reset')
            _send_password_reset(user.email, user.username, tok)
        sent = True
    return render_template('forgot_password.html', sent=sent)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    data = read_token(token, 'pw-reset', max_age=3600)
    if not data:
        return render_template('message.html', title='Link Expired',
                               message='This password reset link is invalid or has expired.')
    user = db.session.get(User, data.get('uid'))
    if not user:
        return render_template('message.html', title='Not Found',
                               message='User not found.')
    error = None
    if request.method == 'POST':
        new = request.form.get('new_password', '')
        con = request.form.get('confirm_password', '')
        if not new:
            error = 'Password is required.'
        elif new != con:
            error = 'Passwords do not match.'
        else:
            user.set_password(new)
            # Lift the suspension now the reset is complete
            user.is_suspended = False
            db.session.commit()
            return render_template('message.html', title='Password Reset',
                                   message='Your password has been reset.',
                                   show_login=True)
    return render_template('reset_password.html', token=token, error=error)


@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at).all()
    return render_template('admin_users.html', users=users, Role=Role)


@app.route('/admin/users/<int:uid>/role', methods=['POST'])
@login_required
@admin_required
def change_role(uid):
    user = db.session.get(User, uid)
    if user and user.id != current_user.id:
        try:
            user.role = Role[request.form.get('role')]
            db.session.commit()
        except KeyError:
            pass
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/reset-password', methods=['POST'])
@login_required
@admin_required
def admin_reset_password(uid):
    user = db.session.get(User, uid)
    if user and user.id != current_user.id:
        user.is_suspended = True
        db.session.commit()
        tok = make_token({'uid': user.id}, 'pw-reset')
        _send_password_reset(user.email, user.username, tok)
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/suspend', methods=['POST'])
@login_required
@admin_required
def suspend_user(uid):
    user = db.session.get(User, uid)
    if user and user.id != current_user.id:
        user.is_suspended = not user.is_suspended
        db.session.commit()
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:uid>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(uid):
    user = db.session.get(User, uid)
    if user and user.id != current_user.id:
        db.session.delete(user)
        db.session.commit()
    return redirect(url_for('admin_users'))


# Email helpers

def _send(to, subject, template, **kwargs):
    try:
        msg = Message(subject=subject, recipients=[to],
                      html=render_template(template, **kwargs))
        mail.send(msg)
    except Exception as e:
        app.logger.error(f'Mail error: {e}')


def _send_approval_request(admin_email, new_user, new_email,
                            approve_tok, deny_tok):
    _send(admin_email, f'New registration: {new_user}',
          'emails/approval_request.html',
          new_user=new_user, new_email=new_email,
          approve_url=f'{BASE_URL}/admin/action/{approve_tok}',
          deny_url=f'{BASE_URL}/admin/action/{deny_tok}')


def _send_verification(user_email, username, token):
    _send(user_email, 'Verify your email – Adaptive Realtime Trading',
          'emails/verification.html',
          username=username,
          verify_url=f'{BASE_URL}/verify/{token}')


def _send_username_reminder(user_email, username):
    _send(user_email, 'Your username – Adaptive Realtime Trading',
          'emails/username_reminder.html',
          username=username, login_url=BASE_URL)


def _send_password_reset(user_email, username, token):
    _send(user_email, 'Password reset – Adaptive Realtime Trading',
          'emails/password_reset.html',
          username=username,
          reset_url=f'{BASE_URL}/reset-password/{token}')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='127.0.0.1', port=8002, debug=False)
