import { setupServer } from "msw/node";

/**
 * Default MSW server — individual tests register route-level handlers via
 * ``server.use(...)``. The ``setup.ts`` hook resets handlers between tests so
 * leakage is not possible.
 */
export const server = setupServer();
