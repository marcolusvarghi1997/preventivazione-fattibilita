from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from apps.quotes.models import Quote
from .pdf import build_customer_pdf


@login_required
@permission_required("quotes.generate_quote_pdf", raise_exception=True)
def quote_pdf(request, pk: int) -> HttpResponse:
    quote = get_object_or_404(
        Quote.objects.select_related("client").prefetch_related("items__materials__material", "items__phases__definition", "items__phases__treatments"),
        pk=pk,
        **({} if request.user.is_superuser else {"author": request.user}),
    )
    response = HttpResponse(build_customer_pdf(quote), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="Preventivo_{quote.number}.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
