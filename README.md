# Website Authentication Template

A Flask-based web authentication template with role management, email workflows, and user administration. Built as the authentication foundation for [scalping.adaptiverealtimetrading.co.uk](https://scalping.adaptiverealtimetrading.co.uk).

---

## Features

### Authentication
- Login page with site name as title
- Username and password authentication backed by a SQLite database
- Successful login redirects to a blank landing page ready for content
- Failed login replaces the registration link with **"Forgotten username or password"**, where each word is independently clickable

### User Roles
Three roles are supported:
| Role | Description |
|---|---|
| **Admin** | Full access including user management |
| **Trader** | Standard authenticated access |
| **Monitor** | Default role assigned to new registrations |

The **first user to register** is automatically granted the Admin role. All subsequent registrations are assigned the Monitor role.

### Registration Flow
1. New user completes the registration form (username, email, password, confirm password — all mandatory)
2. An approval request email is sent to all Admin users containing **Approve** and **Deny** buttons
3. If approved, a verification email is sent to the new user with a **Verify** button
4. Once the user verifies their email, their account is activated and they can log in
5. If denied, the registration is removed from the database

### Forgotten Credentials
- **Forgotten username** — user enters their email address and receives an email containing their username and a login button
- **Forgotten password** — user enters their email address; their account is **immediately suspended** and they receive a password reset link. The account is automatically unsuspended once they successfully set a new password

### Profile Page
Accessible via the profile icon in the top navigation bar. Displays:
- Username and role badge
- **Change Email** card — update the account email address
- **Change Password** card — requires current password, new password, and confirmation

### Password Visibility Toggle
All password entry fields across the site include an **eye icon** toggle that allows the user to reveal or hide what they are typing. Each field operates independently.

### Navigation Dropdown
Hovering over the profile icon in the top bar reveals a dropdown menu containing:
- **Profile** — navigate to the profile page
- **User Management** *(Admin only)* — navigate to the user administration page
- **Home** — return to the landing page
- **Logout** — end the session

### User Management *(Admin only)*
Accessible from the profile dropdown. Displays a table of all registered users with the following controls per user:

| Control | Action |
|---|---|
| **Role dropdown** | Change the user's role (Admin / Trader / Monitor). Takes effect immediately |
| **Suspend / Unsuspend** | Toggles access. A suspended user cannot log in |
| **Reset Password** | Suspends the user's account and sends them a password reset email. The account is unsuspended automatically once they set a new password |
| **Delete** | Permanently removes the user from the database |

Admins cannot modify, suspend, reset, or delete their own account from this page.

---

## Email Workflows

The following automated emails are sent by the system:

| Trigger | Recipient | Content |
|---|---|---|
| New registration | All Admins | Approve / Deny buttons |
| Admin approves user | New user | Email verification link |
| Forgotten username | Requesting user | Username and login button |
| Forgotten password | Requesting user | Password reset link (account suspended until used) |
| Admin resets password | Affected user | Password reset link (account suspended until used) |

---

## Tech Stack

- **Framework:** Flask 3.1
- **Database:** SQLAlchemy with SQLite
- **Authentication:** Flask-Login
- **Email:** Flask-Mail (SMTP)
- **Tokens:** itsdangerous (URL-safe timed tokens for all email links)
- **Password hashing:** Werkzeug
- **Server:** Gunicorn behind Nginx with Let's Encrypt SSL

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/ljones-adaptive/WebiteAuthenticationTemplate.git
cd WebiteAuthenticationTemplate
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
SECRET_KEY=your-long-random-secret-key
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-app-password
MAIL_DEFAULT_SENDER=your-email@example.com
BASE_URL=https://your-domain.com
```

### 3. Initialise the database and run

```bash
python app.py
```

The database is created automatically on first run. Navigate to `http://localhost:8002` and register the first account — it will be granted Admin role automatically.

### 4. Production deployment (Nginx + Gunicorn)

Run with Gunicorn:

```bash
gunicorn --workers 2 --bind 127.0.0.1:8002 app:app
```

Example Nginx server block:

```nginx
server {
    server_name your-domain.com;

    location / {
        proxy_pass         http://127.0.0.1:8002;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    listen 443 ssl;
    # Add your SSL certificate paths here
}
```

Add SSL with Certbot:

```bash
sudo certbot --nginx -d your-domain.com
```

---

## Security Notes

- Never commit your `.env` file — it is excluded via `.gitignore`
- Password reset and email verification links expire after **1 hour** (approval links after **24 hours**)
- Requesting a password reset immediately suspends the account until the reset is completed
- All passwords are hashed using Werkzeug's `generate_password_hash`
