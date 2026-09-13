import pptxgen from 'pptxgenjs';
import { chapters, REVISION } from '../src/story';

export async function exportPowerPoint() {
  const deck = new pptxgen();
  deck.layout = 'LAYOUT_WIDE';
  deck.author = 'AFTERLAP';
  deck.subject = 'Implementation and recorded product demo';
  deck.title = 'AFTERLAP implementation';
  deck.company = 'AFTERLAP';
  for (const [index, chapter] of chapters.entries()) {
    const slide = deck.addSlide();
    slide.addImage({ path: `dist/slides/${String(index + 1).padStart(2, '0')}.jpg`, x: 0, y: 0, w: 13.333333, h: 7.5, altText: `${chapter.title.replace('\n', ' ')}. ${chapter.body} ${chapter.caption}` });
    slide.addNotes(`${chapter.title.replace('\n', ' ')}\n\n${chapter.body}\n\n${chapter.caption}\n\n${chapter.notes}\n\nSources:\n${chapter.sources.map((path) => `https://github.com/Manas-thakur/f1/blob/${REVISION}/${path}`).join('\n')}`);
  }
  await deck.writeFile({ fileName: 'dist/show-shah.pptx', compression: true });
}

if (import.meta.main) await exportPowerPoint();
