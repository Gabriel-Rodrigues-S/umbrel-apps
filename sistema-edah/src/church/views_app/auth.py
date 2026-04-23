from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse

from church.forms import EmailAuthenticationForm
from church.rate_limit import check_rate_limit, reset_rate_limit


RATE_LIMIT_LOGIN_TENTATIVAS = 5
RATE_LIMIT_LOGIN_WINDOW_SECONDS = 60


class ChurchLoginView(LoginView):
    template_name = "app/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        is_limited, retry_after = check_rate_limit(
            request,
            scope="login",
            limit=RATE_LIMIT_LOGIN_TENTATIVAS,
            window_seconds=RATE_LIMIT_LOGIN_WINDOW_SECONDS,
        )
        if is_limited:
            response = HttpResponse("Muitas tentativas de login. Tente novamente em instantes.", status=429)
            response["Retry-After"] = str(retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        reset_rate_limit(self.request, scope="login")
        return super().form_valid(form)


class ChurchLogoutView(LogoutView):
    next_page = "login"
