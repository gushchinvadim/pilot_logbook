"""Bounded HTTPS export client; never follows redirects with a credential."""
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode, urlsplit
from django.conf import settings
from rest_framework.exceptions import APIException


class ATCDError(APIException):
    status_code = 502
    default_detail = 'Не удалось получить расписание ATCD. Проверьте подключение и настройки интеграции.'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_schedule(start, end):
    base = settings.ATCD_BASE_URL.rstrip('/')
    url = urlsplit(base)
    local = settings.DEBUG and url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')
    if not ((url.scheme == 'https' and url.hostname == 'nordstar.atcdocs.ru') or local) or url.username or url.password or url.path or url.query or url.fragment:
        raise ATCDError('Неверный адрес ATCD. Используйте https://nordstar.atcdocs.ru или локальный сервер в режиме разработки.')
    if len(settings.ATCD_EXPORT_KEY) < 32:
        raise ATCDError('Интеграция ATCD ещё не настроена на сервере.')
    request = Request(base + '/api/integrations/sim-training/schedule/?' + urlencode({'from': start, 'to': end}),
                      headers={'X-SIM-Integration-Key': settings.ATCD_EXPORT_KEY, 'Accept': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError()
        data = json.loads(raw)
        if data.get('schema') != 1 or data.get('source') != 'nordstar-atcd' or not isinstance(data.get('rows'), list) or len(data['rows']) > 1000:
            raise ValueError()
        ids = [row['id'] for row in data['rows']]
        if any(type(v) is not int or v <= 0 for v in ids) or len(set(ids)) != len(ids): raise ValueError()
        return data['rows']
    except Exception:
        raise ATCDError() from None
