function upstreamUrl() {
  const upstream = process.env['AFTERLAP_RACE_UPSTREAM'] ?? 'http://127.0.0.1:18761';
  return new URL('boost', upstream.endsWith('/') ? upstream : `${upstream}/`);
}

export async function POST() {
  try {
    const response = await fetch(upstreamUrl(), { method: 'POST', cache: 'no-store' });
    const payload = await response.text();
    return new Response(payload, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('Content-Type') ?? 'application/json' },
    });
  } catch {
    return Response.json({ error: 'race runtime unavailable' }, { status: 502 });
  }
}
