import { createAvatarServer } from './app.mjs';
import { readConfig } from './config.mjs';

const config = readConfig();
const server = createAvatarServer({ config });
server.listen(config.port, config.host, () => {
  console.log(`Savia avatar is ready at ${config.publicOrigin || `http://${config.host}:${config.port}`}`);
});
server.on('error', error => {
  // No request content, upstream body, cookies or keys enter application logs.
  console.error(`Avatar server could not listen (${error.code || 'unknown'}).`);
  process.exitCode = 1;
});

let stopping = false;
const shutdown = () => {
  if (stopping) return;
  stopping = true;
  server.close();
  server.closeIdleConnections();
  const deadline = setTimeout(() => { server.closeAllConnections(); process.exit(0); }, 5000);
  deadline.unref();
};
process.once('SIGINT', shutdown);
process.once('SIGTERM', shutdown);
