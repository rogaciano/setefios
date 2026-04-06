from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import RedirectView, TemplateView

from sales.models import Order, Product

from .forms import CompanyForm, SupplierForm, SupplierImportProfileFormSet
from .models import Company, Supplier


class HomeRedirectView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return reverse("dashboard")
        return reverse("login")


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        product_qs = Product.objects.filter(is_active=True).select_related("category")
        order_qs = Order.objects.all().select_related("buyer_company", "participant")

        aggregates = order_qs.aggregate(
            sales_total=Sum("total_amount"),
            pieces_total=Sum("total_pieces"),
        )

        context.update(
            {
                "client_total": Company.objects.filter(is_active=True).count(),
                "product_total": product_qs.count(),
                "order_total": order_qs.count(),
                "sales_total": aggregates["sales_total"] or Decimal("0.00"),
                "pieces_total": aggregates["pieces_total"] or 0,
                "recent_orders": order_qs.order_by("-created_at")[:5],
                "product_highlights": product_qs.order_by("description")[:6],
            }
        )
        return context


@login_required
def client_list(request):
    query = request.GET.get("q", "").strip()
    clients = Company.objects.order_by("trade_name", "legal_name")

    if query:
        clients = clients.filter(
            Q(trade_name__icontains=query)
            | Q(legal_name__icontains=query)
            | Q(cnpj__icontains=query)
            | Q(email__icontains=query)
        )

    return render(
        request,
        "core/client_list.html",
        {
            "clients": clients,
            "query": query,
        },
    )


@login_required
def client_form(request, pk=None):
    company = get_object_or_404(Company, pk=pk) if pk else Company()
    is_edit = bool(pk)

    form = CompanyForm(request.POST or None, instance=company)

    if request.method == "POST" and form.is_valid():
        form.save()
        action = "atualizado" if is_edit else "cadastrado"
        messages.success(request, f"Cliente {action} com sucesso.")
        return redirect("core:client_list")

    return render(
        request,
        "core/client_form.html",
        {
            "form": form,
            "company": company if is_edit else None,
        },
    )


@login_required
def supplier_list(request):
    query = request.GET.get("q", "").strip()
    suppliers = Supplier.objects.annotate(
        import_profile_total=Count("import_profiles", filter=Q(import_profiles__is_active=True))
    ).order_by("trade_name")

    if query:
        suppliers = suppliers.filter(
            Q(trade_name__icontains=query)
            | Q(cnpj__icontains=query)
            | Q(contact_name__icontains=query)
        )

    return render(
        request,
        "core/supplier_list.html",
        {
            "suppliers": suppliers,
            "query": query,
        },
    )


@login_required
def supplier_form(request, pk=None):
    supplier = get_object_or_404(Supplier, pk=pk) if pk else Supplier()
    is_edit = bool(pk)

    form = SupplierForm(request.POST or None, instance=supplier)
    profile_formset = SupplierImportProfileFormSet(
        request.POST or None,
        instance=supplier,
        prefix="profiles",
    )

    if request.method == "POST" and form.is_valid() and profile_formset.is_valid():
        saved_supplier = form.save()
        profile_formset.instance = saved_supplier
        profile_formset.save()
        action = "atualizado" if is_edit else "cadastrado"
        messages.success(request, f"Fornecedor {action} com sucesso.")
        return redirect("core:supplier_list")

    return render(
        request,
        "core/supplier_form.html",
        {
            "form": form,
            "supplier": supplier if is_edit else None,
            "profile_formset": profile_formset,
        },
    )
