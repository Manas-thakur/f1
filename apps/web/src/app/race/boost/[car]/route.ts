const CAR_ID = /^car-[0-9]{2}$/;

function upstreamUrl(carId: string) {
  const upstream = process.env['AFTERLAP_RACE_UPSTREAM'] ?? 'http://127.0.0.1:18761';
  return new URL(`boost/${carId}`, upstream.endsWith('/') ? upstream : `${upstream}/`);
}

export async function POST(
  _request: Request,
  context: { readonly params: Promise<{ readonly car: string }> },
) {
  const { car } = await context.params;
  if (!CAR_ID.test(car)) {
    return Response.json({ error: 'invalid car id' }, { status: 400 });
  }
  try {
    const response = await fetch(upstreamUrl(car), { method: 'POST', cache: 'no-store' });
    const payload = await response.text();
    return new Response(payload, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('Content-Type') ?? 'application/json' },
    });
  } catch {
    return Response.json({ error: 'race runtime unavailable' }, { status: 502 });
  }
}
