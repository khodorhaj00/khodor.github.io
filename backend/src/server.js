import { createApp, VERSION } from './app.js';
import { createComputeClient } from './compute.js';
import { loadConfig } from './config.js';
import { createLogger } from './logger.js';
import { rhinoReady } from './rhino.js';

const config = loadConfig(process.env);
const logger = createLogger(config.logLevel);

const compute = config.computeUrl
  ? createComputeClient({ url: config.computeUrl, apiKey: config.computeApiKey, timeoutMs: config.computeTimeoutMs })
  : null;

const rhino = await rhinoReady;
const app = createApp({ config, compute, logger });

const server = app.listen(config.port, () => {
  logger.info({
    msg: 'listening',
    version: VERSION,
    port: server.address().port,
    rhino3dm: rhino.Version,
    compute: compute ? compute.url : null,
    maxUploadMb: config.maxUploadMb,
    meshQuality: config.meshQuality,
  });
});
// Uploads of a couple hundred MB over a workshop Wi-Fi can take longer than Node's 5-minute default.
server.requestTimeout = 600000;
server.headersTimeout = 65000;

function shutdown(signal) {
  logger.info({ msg: 'shutting down', signal });
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 10000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
