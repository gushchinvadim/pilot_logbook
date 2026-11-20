import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openPrintDocument } from '../src/lib/printDocument.js';

function browser(t) {
  const calls = { closed: 0 };
  const popup = {
    closed: false,
    opener: {},
    location: { replace(url) { calls.navigation = url; } },
    close() { this.closed = true; calls.closed++; },
  };
  const oldWindow = globalThis.window;
  globalThis.window = {
    open: () => popup,
    location: { href: 'http://localhost:5174/results', origin: 'http://localhost:5174' },
  };
  t.after(() => { globalThis.window = oldWindow; });
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.path = path; calls.options = options;
    return { ok: true, json: async () => ({url: '/api/results/7/print/'}) };
  });
  return { calls, popup };
}

test('navigates to server HTML with the selected revision and no token in URL', async (t) => {
  const { calls, popup } = browser(t);
  await openPrintDocument('/api/results/7/print/?revision=9', 'secret-test-token');
  assert.equal(calls.navigation, 'http://localhost:5174/api/results/7/print/?revision=9');
  assert.equal(calls.path, '/api/results/7/print-access/');
  assert.equal(calls.options.method, 'POST');
  assert.equal(calls.options.credentials, 'same-origin');
  assert.equal(calls.options.headers.Authorization, 'Token secret-test-token');
  assert.ok(!calls.navigation.includes('secret-test-token'));
  assert.equal(popup.opener, null);
});

test('closes the popup on an unsuccessful protected request', async (t) => {
  const { calls } = browser(t);
  t.mock.method(globalThis, 'fetch', async () => ({ ok: false }));
  await assert.rejects(openPrintDocument('/api/results/7/print/', 'token'), /Не удалось/);
  assert.equal(calls.closed, 1);
  assert.equal(calls.navigation, undefined);
});

test('reports blocked popups before sending a request', async (t) => {
  const { calls } = browser(t);
  window.open = () => null;
  await assert.rejects(openPrintDocument('/api/results/7/print/', 'token'), /Разрешите/);
  assert.equal(calls.path, undefined);
});

test('does not navigate a tab closed while fetching', async (t) => {
  const { calls, popup } = browser(t);
  popup.closed = true;
  await openPrintDocument('/api/results/7/print/', 'token');
  assert.equal(calls.navigation, undefined);
});

test('rejects unexpected print destinations', async (t) => {
  const { calls } = browser(t);
  t.mock.method(globalThis, 'fetch', async () => ({ok: true, json: async () => ({url: 'https://example.com/print/'})}));
  await assert.rejects(openPrintDocument('/api/results/7/print/', 'token'), /Неверный адрес/);
  assert.equal(calls.navigation, undefined);
  assert.equal(calls.closed, 1);
});
