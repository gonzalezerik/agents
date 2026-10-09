/**
 * Vitest setup: point the orchestration DB at a temp dir before any module loads.
 * This file runs before each test file via setupFiles in vitest.config.ts.
 * Added for Stage A test infrastructure only — does not change production behavior.
 */
import os from "os";
import path from "path";
import fs from "fs";

const testDir = path.join(os.tmpdir(), `mc-test-${process.pid}`);
fs.mkdirSync(testDir, { recursive: true });
process.env.MC_STATE_DIR = testDir;
