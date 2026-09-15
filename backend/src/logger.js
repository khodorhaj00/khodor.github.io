import { LOG_LEVELS } from './config.js';

/**
 * Minimal JSON-lines logger. Every record is one line on stdout (stderr for `error`),
 * so `docker logs` and log shippers can parse it without configuration.
 */
export function createLogger(level = 'info', { stdout = process.stdout, stderr = process.stderr } = {}) {
  const threshold = LOG_LEVELS.indexOf(level);

  function emit(recordLevel, fields) {
    if (LOG_LEVELS.indexOf(recordLevel) > threshold) return;
    const line = `${JSON.stringify({ ts: new Date().toISOString(), level: recordLevel, ...fields })}\n`;
    (recordLevel === 'error' ? stderr : stdout).write(line);
  }

  return {
    level,
    error: (fields) => emit('error', fields),
    warn: (fields) => emit('warn', fields),
    info: (fields) => emit('info', fields),
    debug: (fields) => emit('debug', fields),
  };
}

export const silentLogger = { level: 'error', error() {}, warn() {}, info() {}, debug() {} };
