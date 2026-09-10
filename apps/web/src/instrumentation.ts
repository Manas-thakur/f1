export async function register(): Promise<void> {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { ensurePythonRuntime } = await import('./server/python');
    try {
      await ensurePythonRuntime();
    } catch {
      return;
    }
  }
}
