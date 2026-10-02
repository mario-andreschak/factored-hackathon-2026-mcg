import http from 'node:http';
import { pathToFileURL } from 'node:url';

export const LOCAL_ORIGIN = 'http://localhost:43800';
const HOP = new Set(['connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade']);

export function admittedRequest(method, url, headers) {
  if (headers.host !== 'localhost:43800' || typeof url !== 'string'
    || !url.startsWith('/') || url.startsWith('//') || /[\\\r\n\0]/.test(url)
    || !['GET', 'HEAD', 'POST', 'OPTIONS'].includes(method)) return false;
  let parsed;
  try { parsed = new URL(url, LOCAL_ORIGIN); } catch { return false; }
  if (parsed.origin !== LOCAL_ORIGIN || /^\/(?:v1|_fly|_next|mcp)(?:\/|$)/.test(parsed.pathname)) return false;
  if (headers.origin && headers.origin !== LOCAL_ORIGIN) return false;
  if (headers['sec-fetch-site'] === 'cross-site') return false;
  return ['GET', 'HEAD', 'OPTIONS'].includes(method) || headers.origin === LOCAL_ORIGIN;
}

export function createLocalProxy() {
  const server = http.createServer((request, response) => {
    if (!admittedRequest(request.method, request.url, request.headers)) {
      response.writeHead(403, { 'content-type': 'text/plain', 'cache-control': 'no-store' });
      response.end('Local request denied.'); return;
    }
    const headers = Object.fromEntries(Object.entries(request.headers).filter(([name]) =>
      !HOP.has(name) && !name.startsWith('x-forwarded-') && !name.startsWith('x-flujo-')
      && !['forwarded', 'x-workspace'].includes(name)));
    headers.host = 'localhost:43800';
    // Only Savia's listener is reachable. Never forward to the native worker.
    const upstream = http.request({ host: '127.0.0.1', port: 8082,
      method: request.method, path: request.url, headers }, result => {
      const returned = Object.fromEntries(Object.entries(result.headers).filter(([name]) => !HOP.has(name)));
      response.writeHead(result.statusCode || 502, returned); result.pipe(response);
      result.once('error', () => response.destroy());
    });
    upstream.once('error', () => {
      if (!response.headersSent) response.writeHead(502, { 'content-type': 'text/plain', 'cache-control': 'no-store' });
      response.end('Application unavailable.');
    });
    request.once('aborted', () => upstream.destroy());
    response.once('close', () => { if (!response.writableEnded) upstream.destroy(); });
    request.pipe(upstream);
  });
  server.on('upgrade', (_request, socket) => socket.destroy());
  return server;
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  const server = createLocalProxy();
  server.listen(8080, '0.0.0.0');
  const stop = () => { server.close(); server.closeAllConnections(); };
  process.once('SIGTERM', stop); process.once('SIGINT', stop);
}
