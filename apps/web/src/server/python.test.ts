import { beforeEach, describe, expect, it, vi } from 'vitest';

const spawn = vi.hoisted(() => vi.fn());
vi.mock('node:child_process', () => ({ spawn, default: { spawn } }));

import { forwardToPython } from './python';

describe('HTTP bridge input and failure boundaries', () => {
  beforeEach(() => {
    spawn.mockReset();
    vi.stubEnv('AFTERLAP_AUTOSTART_RUNTIME', '0');
  });

  it('rejects oversized UTF-8 bodies before starting Python', async () => {
    const request = new Request('http://localhost/api/v1/sessions', {
      method: 'POST',
      body: 'x'.repeat(65_537),
    });
    const response = await forwardToPython(request, 'POST', '/api/v1/sessions');
    expect(response.status).toBe(413);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('counts encoded bytes instead of character length', async () => {
    const request = new Request('http://localhost/api/v1/sessions', {
      method: 'POST',
      body: '\u03b1'.repeat(32_769),
    });
    expect((await forwardToPython(request, 'POST', '/api/v1/sessions')).status).toBe(413);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('rejects malformed UTF-8', async () => {
    const request = new Request('http://localhost/api/v1/sessions', {
      method: 'POST',
      body: new Uint8Array([0xff]),
    });
    expect((await forwardToPython(request, 'POST', '/api/v1/sessions')).status).toBe(400);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('returns a typed unavailable response without leaking process errors', async () => {
    spawn.mockImplementation(() => {
      throw new Error('private/path/credential');
    });
    const request = new Request('http://localhost/api/v1/sessions');
    const response = await forwardToPython(request, 'GET', '/api/v1/sessions');
    expect(response.status).toBe(503);
    const text = await response.text();
    expect(text).toContain('capability_unavailable');
    expect(text).not.toContain('credential');
  });
});
