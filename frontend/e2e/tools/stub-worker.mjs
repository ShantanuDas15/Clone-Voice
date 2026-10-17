// Health-only stand-in for the Chatterbox inference worker, so the real backend reports a healthy
// expressive engine (and the delivery controls appear) without a GPU or the worker's environment.
// It answers GET /health only; synthesis is not offered. Usage: node e2e/tools/stub-worker.mjs
// (see e2e/README.md, "Expressive engine"). The model name must equal the engine's: `original`.
import http from "node:http";

const PORT = Number(process.env.STUB_WORKER_PORT ?? 9100);

http
  .createServer((req, res) => {
    const ok = req.url === "/health";
    res.writeHead(ok ? 200 : 404, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify(
        ok ? { ready: true, model: "original", device: "cpu", sample_rate: 24000 } : {},
      ),
    );
  })
  .listen(PORT, "127.0.0.1", () => console.log(`stub worker on http://127.0.0.1:${PORT}`));
