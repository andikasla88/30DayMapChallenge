// Day 04: SSIC titles from SingStat's classification-structure workbook, unzipped.
// usage: node ssic.mjs <unzipped xlsx dir>      prints {"86203": "Specialised medical services", ...}
import { readFileSync } from 'node:fs';
const d = process.argv[2];
const unxml = s => s.replace(/&amp;/g, '&').replace(/&apos;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const ss = [...readFileSync(d + '/xl/sharedStrings.xml', 'utf8').matchAll(/<si>([\s\S]*?)<\/si>/g)]
  .map(m => unxml([...m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)].map(x => x[1]).join('')));
const out = {};
for (const row of readFileSync(d + '/xl/worksheets/sheet1.xml', 'utf8').matchAll(/<row[^>]*>([\s\S]*?)<\/row>/g)) {
  const cells = [...row[1].matchAll(/<c r="[A-Z]+\d+"([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)].map(c => {
    const v = (c[2] || '').match(/<v>([\s\S]*?)<\/v>/)?.[1] ?? (c[2] || '').match(/<t[^>]*>([\s\S]*?)<\/t>/)?.[1];
    return /t="s"/.test(c[1]) ? ss[+v] : v;
  });
  const i = cells.findIndex(x => /^\d{5}$/.test(String(x || '').trim()));   // a 5-digit sub-class, then its title
  if (i >= 0) out[String(cells[i]).trim()] = String(cells.slice(i + 1).find(x => x && isNaN(x)) || '').trim();
}
console.log(JSON.stringify(out));
