// The four cities, shared by fetch.js and build.js. Every map shows the same 56 x 48 km of
// ground (the poster's panels are 7 : 6), centred on the city.
'use strict';
const FRAME_KM = [56, 48];
const list = [
  { id: 'singapore', name: 'Singapore', centre: [103.835, 1.352], area: '["ISO3166-1"="SG"][boundary=administrative]' },
  { id: 'hongkong', name: 'Hong Kong', centre: [114.13, 22.35], area: '["ISO3166-1"="HK"][boundary=administrative]' },
  { id: 'stockholm', name: 'Stockholm', centre: [18.03, 59.33], area: '["ISO3166-1"="SE"][boundary=administrative]' },
  { id: 'copenhagen', name: 'Copenhagen', centre: [12.47, 55.7], area: '["ISO3166-1"="DK"][boundary=administrative]' },
];
// [west, south, east, north] of the frame, plus a margin in km.
function bbox(c, marginKm = 0) {
  const [lng, lat] = c.centre;
  const dy = (FRAME_KM[1] / 2 + marginKm) / 110.574, dx = (FRAME_KM[0] / 2 + marginKm) / (111.32 * Math.cos(lat * Math.PI / 180));
  return [lng - dx, lat - dy, lng + dx, lat + dy].map(v => Math.round(v * 1e4) / 1e4);
}
module.exports = { FRAME_KM, list, bbox };
