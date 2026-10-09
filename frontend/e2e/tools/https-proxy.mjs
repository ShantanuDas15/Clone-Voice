// Local TLS terminator so WebKit (which drops `Secure` cookies over http://localhost) can run the
// e2e suite: https://localhost:3443 -> web :3000 and https://localhost:8443 -> API :8000.
// Usage: node e2e/tools/https-proxy.mjs <key.pem> <cert.pem>   (see e2e/README.md)
import fs from "node:fs";
import http from "node:http";
import https from "node:https";

const [keyFile, certFile] = process.argv.slice(2);
if (!keyFile || !certFile) {
  console.error("usage: node e2e/tools/https-proxy.mjs <key.pem> <cert.pem>");
  process.exit(1);
}
const tls = { key: fs.readFileSync(keyFile), cert: fs.readFileSync(certFile) };

for (const [from, to] of [
  [3443, 3000],
  [8443, 8000],
]) {
  https
    .createServer(tls, (req, res) => {
      const upstream = http.request(
        { host: "127.0.0.1", port: to, path: req.url, method: req.method, headers: req.headers },
        (r) => {
          res.writeHead(r.statusCode ?? 502, r.headers);
          r.pipe(res);
        },
      );
      upstream.on("error", () => {
        res.statusCode = 502;
        res.end();
      });
      req.pipe(upstream);
    })
    .listen(from, () => console.log(`https://localhost:${from} -> http://127.0.0.1:${to}`));
}
