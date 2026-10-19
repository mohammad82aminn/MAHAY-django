# MAHAY

سایت آموزش و خدمات مهندسی: فروش دوره و پروژهٔ آماده، سفارش پروژهٔ سفارشی، مشاوره، و درخواست همکاری با مجموعه.

رابط کاربری دوزبانه است (فارسی در آدرس‌های عادی، انگلیسی زیر `/en/`). پنل مدیریت و خود محتوا فارسی‌اند.

**پشته:** Django 5.2 · PostgreSQL · CSS دست‌نویس · درگاه زرین‌پال

جزئیات معماری، نقش‌ها و تصمیم‌ها در [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md) است.

## راه‌اندازی محلی

نیازمندی‌ها: Python 3.10+ و PostgreSQL.

```bash
python -m venv venv
venv\Scripts\activate          # ویندوز
# source venv/bin/activate     # لینوکس / مک

pip install -r requirements-dev.txt
```

فایل `.env.example` را به `.env` کپی کن و مقدارها را پر کن. **هرگز `.env` را کامیت نکن.**

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

خروجی را در `SECRET_KEY` بگذار. برای توسعه `DEBUG=True` و `ZARINPAL_MODE=sandbox` کافی است؛ پیامک‌ها در ترمینال چاپ می‌شوند.

دیتابیس را بساز، بعد:

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

ورود با **شماره موبایل** است، نه نام کاربری.

روی ویندوز، جلوی دستورهایی که متن فارسی چاپ می‌کنند `PYTHONIOENCODING=utf-8` بگذار تا کنسول کرش نکند.

## تست

```bash
python manage.py test --noinput --parallel 4
```

دو اجرای تست را هم‌زمان شروع نکن؛ روی یک دیتابیس تست به هم می‌خورند.

## اپ‌ها

| پوشه | نقش |
|---|---|
| `accounts` | کاربر (ورود با موبایل)، OTP، نقش‌ها |
| `domains` | حوزه‌های تخصصی و دسترسی‌ها |
| `products` | دوره و پروژهٔ فروشگاه |
| `content` | درس، پیوست، پیشرفت یادگیری |
| `approvals` | گردش تأیید محتوا |
| `commerce` | سبد، سفارش، پرداخت |
| `services` | سفارش پروژه و مشاوره |
| `pages` | صفحات ثابت و تماس |
| `inbox` | کارپوشهٔ کارکنان |
| `collaboration` | درخواست همکاری |
| `finance` | امور مالی |

## تولید

روی سرور `DEBUG=False` بگذار، `SECRET_KEY` و رمز دیتابیس جدا از محیط توسعه باشد، و `ZARINPAL_MODE=live` فقط وقتی مرچنت واقعی داری.

```bash
python manage.py check --deploy
```
