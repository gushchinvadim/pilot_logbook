// Safari can lose a temporary blob/about:blank document when opening print
// preview. Navigate to server-rendered HTML using a short-lived HttpOnly grant.
export async function openPrintDocument(path, token) {
    const win = window.open('', '_blank');
    if (!win) throw new Error('Разрешите открытие окна для печати.');
    win.opener = null;
    try {
        const source = new URL(path, window.location.href);
        if (source.origin !== window.location.origin || !/\/api\/results\/\d+\/print\/$/.test(source.pathname)) {
            throw new Error('Неверный адрес печати.');
        }
        const response = await fetch(source.pathname.replace(/print\/$/, 'print-access/'), {
            method: 'POST',
            credentials: 'same-origin',
            headers: { Authorization: `Token ${token}` },
        });
        if (!response.ok) throw new Error('Не удалось открыть печатное задание.');
        const { url } = await response.json();
        const target = new URL(url, source.origin);
        if (target.origin !== source.origin || target.pathname !== source.pathname) {
            throw new Error('Неверный адрес печати.');
        }
        target.search = source.search;
        if (!win.closed) win.location.replace(target.href);
    } catch (error) {
        win.close();
        throw error;
    }
}
