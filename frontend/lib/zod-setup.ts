import { z } from "zod";

// Zod 4 probes `new Function("")` to enable JIT validators. A strict CSP reports that probe as a
// violation even though the throw is swallowed, so opt out; validation here is never hot.
// Import this module before building any schema.
z.config({ jitless: true });
