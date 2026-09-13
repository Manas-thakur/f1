import { access, readFile } from 'node:fs/promises';
import { chapters } from '../src/story';
import { clips } from '../src/media';
for (const chapter of chapters) {
  for (const path of chapter.sources) await access(`../${path}`);
  if (chapter.notes.length < 20 || chapter.caption.length < 20) throw new Error(`Incomplete chapter: ${chapter.section}`);
}
for (const clip of Object.values(clips)) {
  await access(`public/${clip}.jpg`);
  await access(`public/${clip}.mp4`);
}
const manifest = JSON.parse(await readFile('public/capture.json', 'utf8'));
if (manifest.clips.length !== Object.keys(clips).length) throw new Error('Capture manifest is incomplete.');
console.log(`${chapters.length} chapters: sources resolve, notes present, ${manifest.clips.length} product clips and screenshots verified.`);
