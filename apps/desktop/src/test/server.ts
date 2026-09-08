import { setupServer } from 'msw/node'

/** Empty by default. Each test installs the handlers it needs via
 *  `server.use(...)`. Any unhandled request fails the test (see setup.ts). */
export const server = setupServer()
