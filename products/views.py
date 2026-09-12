from django.db.models import Count, Prefetch, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView, TemplateView

from content.access import can_manage, can_open
from content.models import Lesson, Section
from domains.models import Domain

from .models import Product, ProductImage

SORTS = {
    "new": ("-created_at", "جدیدترین"),
    "cheap": ("price", "ارزان‌ترین"),
    "expensive": ("-price", "گران‌ترین"),
}


def published_lessons():
    return Lesson.objects.filter(is_published=True, is_archived=False)


class HomeView(TemplateView):
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        visible = Product.objects.visible().select_related("primary_domain")
        context["domains"] = Domain.objects.filter(is_active=True).annotate(
            product_count=Count("products", filter=Q(products__is_published=True, products__is_archived=False))
        )
        context["latest_courses"] = visible.filter(product_type=Product.Type.COURSE)[:8]
        context["latest_projects"] = visible.filter(product_type=Product.Type.PROJECT)[:8]
        context["stats"] = {
            "courses": visible.filter(product_type=Product.Type.COURSE).count(),
            "projects": visible.filter(product_type=Product.Type.PROJECT).count(),
            "domains": len(context["domains"]),
        }
        return context

class ProductListView(ListView):
    """Store list with filters: ?type=course&domain=fpga&q=...&price=free&sort=new"""

    template_name = "products/list.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        params = self.request.GET
        queryset = Product.objects.visible().select_related("primary_domain")

        self.product_type = params.get("type") if params.get("type") in Product.Type.values else ""
        if self.product_type:
            queryset = queryset.filter(product_type=self.product_type)

        self.domain = None
        if params.get("domain"):
            self.domain = get_object_or_404(Domain, slug=params["domain"], is_active=True)
            # Products of the domain + products that are shown in it as a related domain
            queryset = queryset.filter(Q(primary_domain=self.domain) | Q(related_domains=self.domain)).distinct()

        self.query = params.get("q", "").strip()
        if self.query:
            queryset = queryset.filter(Q(title__icontains=self.query) | Q(summary__icontains=self.query))

        self.price = params.get("price", "")
        if self.price == "free":
            queryset = queryset.filter(price=0)
        elif self.price == "paid":
            queryset = queryset.filter(price__gt=0)

        sort = params.get("sort", "")
        self.sort = sort if sort in SORTS else "new"
        return queryset.order_by(SORTS[self.sort][0])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = self.request.GET.copy()
        filters.pop("page", None)
        context.update({
            "types": Product.Type.choices,
            "domains": Domain.objects.filter(is_active=True),
            "sorts": [(key, label) for key, (_, label) in SORTS.items()],
            "current": {"type": self.product_type, "domain": self.domain, "q": self.query,
                        "price": self.price, "sort": self.sort},
            "filters_query": filters.urlencode(),  # keeps filters when changing page
        })
        return context


class ProductDetailView(DetailView):
    template_name = "products/detail.html"
    context_object_name = "product"

    def get_object(self, queryset=None):
        product = get_object_or_404(Product.objects.select_related("primary_domain"), slug=self.kwargs["slug"])
        self.is_preview = not Product.objects.visible().filter(pk=product.pk).exists()
        if self.is_preview and not can_manage(self.request.user, product):
            raise Http404  # drafts are only visible to their managers (as a preview)
        return product

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = context["product"]
        sections = (
            Section.objects.filter(product=product, is_published=True, is_archived=False)
            .prefetch_related(Prefetch("lessons", queryset=published_lessons(), to_attr="visible_lessons"))
        )
        totals = published_lessons().filter(section__in=sections).aggregate(
            count=Count("id"), minutes=Sum("duration_minutes"),
        )
        context.update({
            "is_preview": self.is_preview,
            "sections": sections,
            "lesson_count": totals["count"],
            "total_minutes": totals["minutes"] or 0,
            "gallery": ProductImage.objects.filter(product=product, is_published=True, is_archived=False),
            "related": Product.objects.visible().filter(related_products=product),
            "can_open_files": can_open(self.request.user, product),
        })
        return context