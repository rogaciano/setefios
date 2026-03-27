from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from sales.models import Order

from .forms import WebpicConfigurationForm
from .models import WebpicConfiguration
from .services import WebpicService, WebpicServiceError


def _load_reference_options(config):
    if not config.has_credentials:
        return {}, None

    try:
        return WebpicService(config).fetch_reference_options(), None
    except WebpicServiceError as exc:
        return {}, str(exc)


@login_required
def webpic_dashboard(request):
    config = WebpicConfiguration.get_solo()
    result_kind = None
    result = None

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "save_config":
            form = WebpicConfigurationForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                messages.success(request, "Configuracao operacional da Webpic salva com sucesso.")
                return redirect("integrations:webpic_dashboard")
            messages.error(request, "Revise os campos da configuracao Webpic.")
        else:
            form = WebpicConfigurationForm(instance=config)
            service = WebpicService(config)
            try:
                if action == "import_products":
                    result_kind = "import"
                    result = service.sync_products(user=request.user)
                    report = result["report"]
                    messages.success(
                        request,
                        (
                            "Importacao concluida: "
                            f"{report['imported_total']} novo(s), "
                            f"{report['updated_total']} atualizado(s) e "
                            f"{report['skipped_total']} ignorado(s). "
                            f"Processados sem preco: {report['processed_without_price_total']}. "
                            f"Sem preco valido ignorados: {report['skipped_no_price']}. "
                            f"Sem grade: {report['skipped_no_grades']}."
                        ),
                    )
                elif action == "export_orders":
                    result_kind = "export"
                    result = service.export_pending_orders()
                    success_total = len([row for row in result if row["status"] == "success"])
                    error_total = len([row for row in result if row["status"] == "error"])
                    level = messages.WARNING if error_total else messages.SUCCESS
                    messages.add_message(
                        request,
                        level,
                        f"Exportacao concluida: {success_total} sucesso(s) e {error_total} erro(s).",
                    )
                else:
                    messages.error(request, "Acao invalida para a integracao Webpic.")
            except WebpicServiceError as exc:
                messages.error(request, str(exc))
    else:
        form = WebpicConfigurationForm(instance=config)

    reference_options, options_error = _load_reference_options(config)
    pending_service = WebpicService(config)
    pending_orders = pending_service.pending_orders()[:10]

    return render(
        request,
        "integrations/webpic_dashboard.html",
        {
            "form": form,
            "config": config,
            "reference_options": reference_options,
            "options_error": options_error,
            "result_kind": result_kind,
            "result": result,
            "pending_orders": pending_orders,
            "pending_order_total": pending_service.pending_orders().count(),
        },
    )


@login_required
def webpic_order_payload(request, pk):
    config = WebpicConfiguration.get_solo()
    order = get_object_or_404(Order, pk=pk)

    try:
        payload = WebpicService(config).build_order_payload(order)
    except WebpicServiceError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
