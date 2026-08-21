'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');
const { createRelayServer, parseArgs } = require('./atlas_push_relay');

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise(resolve => server.close(resolve));
}

function request(port, { method = 'GET', path = '/', body = '' } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, method, path }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks).toString() }));
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

test('forwards method, path, query, and body', async t => {
  const upstream = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      res.writeHead(201, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ method: req.method, url: req.url, body: Buffer.concat(chunks).toString() }));
    });
  });
  const upstreamPort = await listen(upstream);
  const relay = createRelayServer({ upstream: `http://127.0.0.1:${upstreamPort}`, allowedHost: '127.0.0.1' });
  const relayPort = await listen(relay);
  t.after(async () => { await close(relay); await close(upstream); });

  const result = await request(relayPort, { method: 'POST', path: '/api/device/result?token=abc', body: '{"ok":true}' });
  assert.equal(result.status, 201);
  assert.deepEqual(JSON.parse(result.body), {
    method: 'POST', url: '/api/device/result?token=abc', body: '{"ok":true}',
  });
});

test('rejects clients other than the configured Atlas host', async t => {
  const relay = createRelayServer({ upstream: 'http://127.0.0.1:1', allowedHost: '192.0.2.1' });
  const relayPort = await listen(relay);
  t.after(async () => { await close(relay); });

  const result = await request(relayPort);
  assert.equal(result.status, 403);
  assert.equal(result.body, 'forbidden');
});

test('parses daemon mode without consuming the next option', () => {
  const options = parseArgs([
    '--daemon', '--bind', '192.168.137.1', '--atlas-host', '192.168.137.100',
    '--upstream', 'http://47.92.195.5',
  ]);
  assert.equal(options.daemon, true);
  assert.equal(options.port, 18080);
});
