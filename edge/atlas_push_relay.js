'use strict';

const http = require('node:http');
const { spawn } = require('node:child_process');

const HOP_BY_HOP_HEADERS = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade',
]);

function normalizedAddress(value) {
  return String(value || '').replace(/^::ffff:/, '');
}

function forwardedHeaders(headers, host) {
  const result = {};
  for (const [name, value] of Object.entries(headers)) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) result[name] = value;
  }
  result.host = host;
  return result;
}

function createRelayServer({ upstream, allowedHost, requestTimeoutMs = 10000 }) {
  const target = new URL(upstream);
  if (target.protocol !== 'http:') throw new Error('Only http upstreams are supported');

  return http.createServer((request, response) => {
    if (normalizedAddress(request.socket.remoteAddress) !== allowedHost) {
      response.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8', 'Content-Length': '9' });
      response.end('forbidden');
      return;
    }

    const upstreamRequest = http.request({
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port || 80,
      method: request.method,
      path: request.url,
      headers: forwardedHeaders(request.headers, target.host),
    }, upstreamResponse => {
      const headers = forwardedHeaders(upstreamResponse.headers, request.headers.host || 'localhost');
      delete headers.host;
      response.writeHead(upstreamResponse.statusCode || 502, headers);
      upstreamResponse.pipe(response);
    });

    upstreamRequest.setTimeout(requestTimeoutMs, () => upstreamRequest.destroy(new Error('upstream timeout')));
    upstreamRequest.on('error', error => {
      if (!response.headersSent) {
        const body = Buffer.from(JSON.stringify({ error: 'upstream_unavailable' }));
        response.writeHead(502, { 'Content-Type': 'application/json', 'Content-Length': body.length });
        response.end(body);
      } else {
        response.destroy(error);
      }
    });
    request.on('error', () => upstreamRequest.destroy());
    request.pipe(upstreamRequest);
  });
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length;) {
    const name = argv[index];
    if (name === '--daemon') {
      values.daemon = true;
      index += 1;
      continue;
    }
    const value = argv[index + 1];
    if (!name || !name.startsWith('--') || value === undefined) throw new Error(`Invalid argument: ${name || ''}`);
    values[name.slice(2)] = value;
    index += 2;
  }
  for (const name of ['bind', 'atlas-host', 'upstream']) {
    if (!values[name]) throw new Error(`Missing --${name}`);
  }
  return {
    bind: values.bind,
    port: Number(values.port || 18080),
    allowedHost: values['atlas-host'],
    upstream: values.upstream,
    daemon: Boolean(values.daemon),
  };
}

if (require.main === module) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.daemon) {
      const args = process.argv.slice(1).filter(value => value !== '--daemon');
      const child = spawn(process.execPath, args, {
        detached: true,
        windowsHide: true,
        stdio: 'ignore',
      });
      child.unref();
      process.exit(0);
    }
    const server = createRelayServer(options);
    server.on('error', error => {
      process.stderr.write(`[relay] ${error.stack || error}\n`);
      process.exitCode = 1;
    });
    server.listen(options.port, options.bind, () => {
      process.stdout.write(`[relay] ${options.bind}:${options.port} -> ${options.upstream}\n`);
    });
  } catch (error) {
    process.stderr.write(`[relay] ${error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { createRelayServer, normalizedAddress, parseArgs };
