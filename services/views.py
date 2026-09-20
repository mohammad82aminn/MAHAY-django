import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.throttle import client_ip
from commerce import gateway

from . import payments, services
from .forms import ServiceRequestForm
from .models import ContactChannel, Referral, RequestPayment, ServiceRequest

# Texts of the two service pages. Same flow, different wording.
PAGES = {
    ServiceRequest.Kind.PROJECT: {
        "title": "سفارش پروژه",
        "lead": "پروژه‌ی خود را به تیم تخصصی MAHAY بسپارید.",
        "intro": [
            "پروژه‌های درسی، پایان‌نامه، صنعتی و استارتاپی را در حوزه‌های تخصصی خود انجام می‌دهیم.",
            "کار می‌تواند انجام کامل پروژه، کمک در بخشی از آن، یا رفع اشکال کاری باشد که شروع کرده‌اید.",
        ],
        "steps": [
            "فرم زیر را پر کنید تا درخواست شما ثبت شود و کد پیگیری بگیرید.",
            "از یکی از راه‌های ارتباطی با ما تماس بگیرید و کد پیگیری را بگویید.",
            "پروژه بررسی می‌شود و زمان و هزینه‌ی آن به شما اعلام می‌گردد.",
            "در صورت توافق، کار به کارشناس حوزه‌ی مربوطه سپرده می‌شود و مستقیم با او در ارتباط خواهید بود.",
        ],
    },
    ServiceRequest.Kind.CONSULTING: {
        "title": "مشاوره تخصصی",
        "lead": "قبل از شروع یا در میانه‌ی کار، با کارشناس همان حوزه مشورت کنید.",
        "intro": [
            "انتخاب مسیر درست، بررسی امکان‌پذیری، انتخاب ابزار و سخت‌افزار، و رفع ابهام‌های فنی.",
            "مشاوره با کارشناس همان حوزه انجام می‌شود و هزینه‌ی آن پس از بررسی موضوع اعلام می‌گردد.",
        ],
        "steps": [
            "فرم زیر را پر کنید تا موضوع مشاوره ثبت شود و کد پیگیری بگیرید.",
            "از یکی از راه‌های ارتباطی با ما تماس بگیرید و کد پیگیری را بگویید.",
            "موضوع بررسی و هزینه‌ی مشاوره اعلام می‌شود.",
            "در صورت توافق، به کارشناس همان حوزه معرفی می‌شوید.",
        ],
    },
}


def request_form(request, kind):
    """The two service pages: intro, form, and our contact IDs."""
    if kind not in PAGES:
        raise Http404
    page = PAGES[kind]

    initial = {}
    if request.user.is_authenticated:
        initial = {
            "name": request.user.get_full_name(),
            "mobile_number": request.user.mobile_number,
            "email": request.user.email or "",
        }

    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES, kind=kind)
        if form.is_valid():
            number = form.cleaned_data["mobile_number"]
            address = client_ip(request)
            if services.too_many_requests(number, address):
                messages.error(request, "درخواست‌های شما زیاد است. یک ساعت دیگر تلاش کنید.")
            else:
                service_request = form.save(commit=False)
                if request.user.is_authenticated:
                    service_request.user = request.user
                service_request.ip_address = address
                service_request.save()
                form.save_m2m()
                services.price_consultation(service_request)
                services.log(service_request, request.user if request.user.is_authenticated else None,
                             "درخواست از طریق فرم سایت ثبت شد.")
                request.session["last_tracking_code"] = service_request.tracking_code
                return redirect("services:submitted", code=service_request.tracking_code)
    else:
        form = ServiceRequestForm(initial=initial, kind=kind)

    return render(request, "services/form.html", {
        "kind": kind, "page": page, "form": form, "channels": active_channels(),
    })


def project_request(request):
    return request_form(request, ServiceRequest.Kind.PROJECT)


def consulting_request(request):
    return request_form(request, ServiceRequest.Kind.CONSULTING)


def submitted(request, code):
    """"Your request is registered — now contact us" page. Only right after submitting."""
    if request.session.get("last_tracking_code") != code:
        raise Http404
    service_request = ServiceRequest.objects.filter(tracking_code=code).first()
    if service_request is None:
        raise Http404
    return render(request, "services/submitted.html", {
        "request_object": service_request, "channels": active_channels(),
    })


@login_required
def my_requests(request):
    requests = (
        ServiceRequest.objects.filter(user=request.user)
        .prefetch_related("domains", "referrals__domain", "payments")
    )
    return render(request, "services/my_requests.html", {
        "requests": [(item, services.stage_of(item)[1], item.due_now) for item in requests],
    })


@login_required
@require_POST
def pay(request, code):
    """Send the customer to the gateway for whatever their request owes right now."""
    service_request = get_object_or_404(ServiceRequest, tracking_code=code)
    if not payments.payable_by(request.user, service_request):
        raise Http404

    callback_url = request.build_absolute_uri(reverse("services:payment_callback"))
    try:
        _payment, payment_url = payments.start(service_request, callback_url)
    except (payments.PaymentNotAllowed, gateway.PaymentError) as error:
        messages.error(request, str(error))
        return redirect("services:my_requests")
    return redirect(payment_url)


def payment_callback(request):
    """
    Where the gateway sends the customer back.

    No login is required: a session can be lost on the way to the bank and back. Nothing here
    trusts the visitor either — the payment is found by the gateway's own authority code, and the
    money is only counted after the gateway confirms it.
    """
    payment = RequestPayment.objects.filter(authority=request.GET.get("Authority", "")).first()
    if payment is None:
        messages.error(request, "پرداخت مورد نظر پیدا نشد.")
        return redirect("home")

    if payment.status == RequestPayment.Status.PAID:  # e.g. the page was refreshed
        messages.info(request, "این پرداخت قبلاً ثبت شده است.")
        return redirect("services:my_requests")

    if request.GET.get("Status") != "OK":
        payments.fail(payment, "پرداخت توسط کاربر لغو شد.")
        messages.warning(request, "پرداخت لغو شد.")
        return redirect("services:my_requests")

    try:
        data = gateway.confirm(payment.amount, payment.authority)
    except gateway.PaymentError as error:
        payments.fail(payment, str(error))
        messages.error(request, f"پرداخت تأیید نشد: {error}")
        return redirect("services:my_requests")

    payments.settle(payment, data)
    messages.success(request, f"پرداخت {payment.amount:,} تومان با موفقیت انجام شد.")
    return redirect("services:my_requests")


@login_required
def attachment(request, kind, pk):
    """The uploaded file of a request / referral: only site admins and the referred experts."""
    models = {"request": ServiceRequest, "referral": Referral}
    if kind not in models:
        raise Http404
    obj = get_object_or_404(models[kind], pk=pk)
    owner = obj if kind == "request" else obj.request
    if not services.can_read(request.user, owner) or not obj.attachment:
        raise Http404
    return FileResponse(obj.attachment.open("rb"), as_attachment=True,
                        filename=os.path.basename(obj.attachment.name))


def active_channels():
    return ContactChannel.objects.filter(is_active=True)