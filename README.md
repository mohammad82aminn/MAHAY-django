# MAHAY

**MAHAY** is a Django-based platform for engineering education and professional services. It brings together a digital marketplace for courses and ready-made projects, custom project requests, expert consultations, and specialist collaboration workflows.

The application is designed around domain-specific teams, role-based permissions, content approval, order processing, and internal administrative workflows.

## Key Features

- **Bilingual website:** Persian (RTL) at the default URLs and English (LTR) under `/en/`. Administrative interfaces and managed content remain in Persian.
- **Education marketplace:** Courses and ready-made projects with sections, lessons, attachments, shopping carts, and orders.
- **Custom project requests:** Request submission, domain-based referrals, expert assignment, pricing review, milestone payments, and case tracking.
- **Expert consultations:** Domain-specific consultation rates and duration-based pricing.
- **Authentication and access control:** Phone-number authentication, verification codes, role-based permissions, and domain-scoped access.
- **Content approval:** Multi-stage review before publication, including manager and administrator decisions.
- **Internal workflows:** Staff messaging, collaboration applications, administrative reports, and pending-task indicators.
- **Finance workflows:** Payment records, configurable revenue-sharing rules, and payout tracking.
- **Protected content:** Access-controlled delivery of purchased learning materials.

## Technology Stack

- **Backend:** Django 5.2, Python 3.10+
- **Database:** PostgreSQL (psycopg 3)
- **Frontend:** Django templates, custom CSS, and JavaScript
- **Payments:** Zarinpal integration with a sandbox mode for development
- **Localization:** Django internationalization and English translation files
- **Testing:** Django's built-in test framework

The project does not require a frontend JavaScript build pipeline.

## Project Structure

| Directory | Purpose |
| --- | --- |
| `config/` | Project settings and URL configuration |
| `accounts/` | User accounts, authentication, and roles |
| `domains/` | Engineering domains and scoped permissions |
| `products/` | Courses and ready-made projects |
| `content/` | Lessons, attachments, and progress tracking |
| `approvals/` | Content review and publication workflows |
| `commerce/` | Cart, orders, payments, and purchases |
| `services/` | Project requests and consultations |
| `pages/` | Public pages and contact forms |
| `inbox/` | Internal staff messaging |
| `collaboration/` | Specialist collaboration requests |
| `finance/` | Receipts, revenue shares, and payouts |

For more detailed architecture and workflow notes, see [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) (currently in Persian).

## Local Development

### Prerequisites

- Python 3.10 or later
- PostgreSQL
- Git

### 1. Clone the repository

```bash
git clone https://github.com/mohammad82aminn/MAHAY-django.git
cd MAHAY-django
```

### 2. Create and activate a virtual environment

```bash
python -m venv venv
```

On Windows (Command Prompt):

```cmd
venv\Scripts\activate
```

On Linux or macOS:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements-dev.txt
```

### 4. Configure environment variables

Copy `.env.example` to `.env` and update the development settings. In Windows Command Prompt:

```cmd
copy .env.example .env
```

On Linux or macOS:

```bash
cp .env.example .env
```

Create a PostgreSQL database matching your `.env` configuration. Configure `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` as needed.

Generate a Django secret key:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Place the generated value in `.env` as `SECRET_KEY`. For local development, use `DEBUG=True`, `SMS_BACKEND=console`, and `ZARINPAL_MODE=sandbox`.

**Never commit `.env`, production credentials, API keys, or database backups.**

### 5. Initialize and run

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` in your browser. User authentication uses phone numbers rather than Django's default username field.

## Running Tests

```bash
python manage.py test --noinput --parallel 4
```

Run only one test suite at a time to avoid interference between concurrent test database operations.

Before any production deployment, review the environment configuration and run:

```bash
python manage.py check --deploy
```

## Current Limitations

- The SMS integration currently supports console-based development behavior; the documented Kavenegar provider is not yet implemented.
- Payment flows have development/test coverage, but a real-money Zarinpal transaction has not been documented as verified.
- The application requires environment-specific configuration and validation before production use.

## Maintenance and Contributions

Maintained by [@mohammad82aminn](https://github.com/mohammad82aminn).

Issues and proposed improvements should describe the problem, expected behavior, and relevant reproduction steps. For changes to authentication, permissions, payments, or protected files, include appropriate automated tests and consider the security implications.
