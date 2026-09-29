/* SQUADUP — service worker: офлайн-оболочка, push-уведомления и фоновая работа.

   Что он умеет:
   • push        — показывает уведомление, даже если приложение закрыто;
   • notificationclick — открывает/фокусирует приложение на нужном экране;
   • badge       — обновляет счётчик на иконке приложения;
   • periodicsync — раз в несколько часов проверяет непрочитанные (если Chrome дал разрешение);
   • sync        — просит открытые вкладки отправить отложенные сообщения из очереди.
   Данные всегда берутся из сети: кэшируются только иконки и офлайн-оболочка.
*/

const CACHE = 'squadup-v12';
const ASSETS = [
  '/',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-maskable-512.png',
  '/icons/apple-touch-icon.png',
  '/icons/favicon-32.png',
  '/icons/favicon-64.png',
];

/* ---------- IndexedDB: маленькое хранилище для фоновых задач ---------- */
function idb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('squadup-sw', 1);
    req.onupgradeneeded = () => req.result.createObjectStore('kv');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function idbGet(key) {
  try {
    const db = await idb();
    return await new Promise((res, rej) => {
      const tx = db.transaction('kv', 'readonly').objectStore('kv').get(key);
      tx.onsuccess = () => res(tx.result);
      tx.onerror = () => rej(tx.error);
    });
  } catch { return null; }
}
async function idbSet(key, value) {
  try {
    const db = await idb();
    await new Promise((res, rej) => {
      const tx = db.transaction('kv', 'readwrite').objectStore('kv').put(value, key);
      tx.onsuccess = () => res();
      tx.onerror = () => rej(tx.error);
    });
  } catch {}
}

/* ---------- установка и обновление ---------- */
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(() => {}).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* ---------- сеть ---------- */
self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;   // данные — только из сети

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put('/', copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then(r => r || caches.match('/')))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then(cached => {
      const network = fetch(req).then(res => {
        if (res && res.ok && url.pathname !== '/sw.js') {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
        }
        return res;
      }).catch(() => cached);
      return cached || network;
    })
  );
});

/* ---------- БЕЙДЖ на иконке приложения ---------- */
/* Внимание: App Badge API поддерживается только на Android, iOS, ChromeOS,
   Windows и macOS. В десктопном Chrome на Linux метод формально существует,
   но его вызов роняет процесс браузера (баг Chromium), а сам бейдж не
   отображается. Поэтому на Linux-десктопе бейдж не трогаем. */
function badgesSupported() {
  const ua = self.navigator.userAgent || '';
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return false;
  return true;
}

async function updateBadge(count) {
  if (!badgesSupported()) return;
  try {
    if (count > 0 && self.navigator.setAppBadge) await self.navigator.setAppBadge(count);
    else if (self.navigator.clearAppBadge) await self.navigator.clearAppBadge();
  } catch {}
}

/* ---------- PUSH: уведомления при закрытом приложении ---------- */
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data && event.data.text() }; }

  const title = data.title || 'SQUADUP';
  const options = {
    body: data.body || 'Новое событие в приложении',
    icon: '/icons/icon-192.png',
    badge: '/icons/favicon-64.png',
    tag: data.tag || 'squadup',
    renotify: true,
    data: { url: data.url || '/' },
    actions: [{ action: 'open', title: 'Открыть' }],
    vibrate: [80, 40, 80],
    lang: 'ru',
  };

  event.waitUntil((async () => {
    // Если приложение открыто и на переднем плане — не дублируем уведомление,
    // только обновляем счётчик.
    const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const focused = clientList.some(c => c.focused);
    if (!focused) await self.registration.showNotification(title, options);
    if (typeof data.badge === 'number') await updateBadge(data.badge);
  })());
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil((async () => {
    const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of clientList) {
      if ('focus' in c) {
        await c.focus();
        if ('navigate' in c) { try { await c.navigate(target); } catch {} }
        return;
      }
    }
    if (self.clients.openWindow) await self.clients.openWindow(target);
  })());
});

self.addEventListener('pushsubscriptionchange', event => {
  // Браузер может обновить подписку — сохраняем новую на сервере.
  event.waitUntil((async () => {
    const token = await idbGet('token');
    if (!token || !event.newSubscription) return;
    const s = event.newSubscription.toJSON();
    await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Token': token },
      body: JSON.stringify({ endpoint: s.endpoint, keys: s.keys }),
    }).catch(() => {});
  })());
});

/* ---------- ФОНОВАЯ синхронизация очереди сообщений ---------- */
self.addEventListener('sync', event => {
  if (event.tag !== 'squadup-outbox') return;
  event.waitUntil((async () => {
    const clientList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    clientList.forEach(c => c.postMessage({ type: 'flush-outbox' }));
    // если открытых окон нет — отправляем очередь прямо из SW
    if (!clientList.length) await flushOutboxInSW();
  })());
});

async function flushOutboxInSW() {
  const token = await idbGet('token');
  const outbox = (await idbGet('outbox')) || [];
  if (!token || !outbox.length) return;
  const rest = [];
  for (const item of outbox) {
    try {
      const res = await fetch(item.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Token': token },
        body: JSON.stringify(item.body),
      });
      if (!res.ok) rest.push(item);
    } catch { rest.push(item); }
  }
  await idbSet('outbox', rest);
}

/* ---------- Периодическая проверка (Chrome, установленное PWA) ---------- */
self.addEventListener('periodicsync', event => {
  if (event.tag !== 'squadup-unread') return;
  event.waitUntil((async () => {
    const token = await idbGet('token');
    if (!token) return;
    try {
      const res = await fetch('/api/me', { headers: { 'X-Token': token } });
      if (!res.ok) return;
      const me = await res.json();
      await updateBadge(me.unread || 0);
      const lastKnown = (await idbGet('lastUnread')) || 0;
      if ((me.unread || 0) > lastKnown) {
        await self.registration.showNotification('Новые сообщения в SQUADUP', {
          body: `У тебя ${me.unread} непрочитанных — загляни в чаты.`,
          icon: '/icons/icon-192.png',
          badge: '/icons/favicon-64.png',
          tag: 'squadup-unread',
          data: { url: '/?view=chats' },
        });
      }
      await idbSet('lastUnread', me.unread || 0);
    } catch {}
  })());
});

/* ---------- сообщения от страницы ---------- */
self.addEventListener('message', event => {
  const msg = event.data || {};
  if (msg.type === 'token') idbSet('token', msg.token);
  if (msg.type === 'outbox') idbSet('outbox', msg.outbox || []);
  if (msg.type === 'badge') updateBadge(msg.count || 0);
});
