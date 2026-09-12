import { TelemetryScreen } from '@/features/telemetry/Screen';

export default async function Page({ params }: { readonly params: Promise<{ car: string }> }) {
  const { car } = await params;
  return <TelemetryScreen carId={decodeURIComponent(car)} />;
}
