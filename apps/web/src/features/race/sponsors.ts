export interface Sponsor {
  id: string;
  label: string;
  image: string | null;
  color: string;
  accent: string;
}

export const SPONSORS: Sponsor[] = [
  { id: 'logo-1', label: 'LOGO 1', image: 'logo-1.jpg', color: '#f5f3ec', accent: '#e02b32' },
  { id: 'logo-2', label: 'LOGO 2', image: 'logo-2.webp', color: '#f5f3ec', accent: '#2f9be0' },
  { id: 'logo-3', label: 'LOGO 3', image: 'logo-3.webp', color: '#f5f3ec', accent: '#f0b429' },
  { id: 'v-max', label: 'V MAX', image: null, color: '#f7f6f1', accent: '#d81f34' },
];

const WORDMARK_WIDTH = 2048;
const WORDMARK_HEIGHT = 512;
const WORDMARK_FACE = '"Arial Black", "Helvetica Neue", Helvetica, Arial, sans-serif';

export function wordmarkCanvas(sponsor: Sponsor) {
  const canvas = document.createElement('canvas');
  canvas.width = WORDMARK_WIDTH;
  canvas.height = WORDMARK_HEIGHT;
  const context = canvas.getContext('2d');
  if (!context) {
    return canvas;
  }
  context.clearRect(0, 0, WORDMARK_WIDTH, WORDMARK_HEIGHT);
  context.textAlign = 'left';
  context.textBaseline = 'middle';
  const bars = 3;
  const barWidth = 52;
  const barGap = 36;
  const slant = 68;
  const left = 96;
  const textLeft = left + bars * (barWidth + barGap) + 60;
  const available = WORDMARK_WIDTH - textLeft - 96;
  let size = 388;
  context.font = `italic 900 ${size}px ${WORDMARK_FACE}`;
  const measured = context.measureText(sponsor.label).width;
  if (measured > available) {
    size = Math.max(96, Math.floor(size * available / measured));
    context.font = `italic 900 ${size}px ${WORDMARK_FACE}`;
  }
  const middle = WORDMARK_HEIGHT / 2;
  const top = middle - WORDMARK_HEIGHT * 0.34;
  const bottom = middle + WORDMARK_HEIGHT * 0.34;
  for (let bar = 0; bar < bars; bar++) {
    const x = left + bar * (barWidth + barGap);
    context.globalAlpha = 0.45 + bar * 0.275;
    context.fillStyle = sponsor.accent;
    context.beginPath();
    context.moveTo(x + slant, top);
    context.lineTo(x + slant + barWidth, top);
    context.lineTo(x + barWidth, bottom);
    context.lineTo(x, bottom);
    context.closePath();
    context.fill();
  }
  context.globalAlpha = 1;
  context.lineJoin = 'round';
  context.lineWidth = size * 0.13;
  context.strokeStyle = 'rgba(10,14,18,0.72)';
  context.strokeText(sponsor.label, textLeft, middle);
  context.fillStyle = sponsor.color;
  context.fillText(sponsor.label, textLeft, middle);
  const metrics = context.measureText(sponsor.label);
  context.fillStyle = sponsor.accent;
  context.fillRect(textLeft - size * 0.03, bottom + WORDMARK_HEIGHT * 0.045,
    metrics.width + size * 0.06, WORDMARK_HEIGHT * 0.06);
  return canvas;
}
