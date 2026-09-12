export interface SceneryProfile {
  terrain: string;
  trees: number;
  conifers: boolean;
  urban: boolean;
  water: boolean;
  night: boolean;
  runoff: string;
  landmark: 'stands' | 'wheel' | 'tower' | 'sphere' | 'hotel' | 'dunes' | 'wing' | 'castle' | 'stadium';
}

const profiles: Record<string, [string, number, boolean, boolean, boolean, boolean, string, SceneryProfile['landmark']]> = {
  austin: ['#8b9560', 180, false, false, false, false, '#344f68', 'tower'],
  baku: ['#938e7b', 60, false, true, true, false, '#575a5b', 'castle'],
  catalunya: ['#8f9467', 240, false, false, false, false, '#b6a789', 'stands'],
  hungaroring: ['#71904f', 450, false, false, false, false, '#b5a891', 'stands'],
  interlagos: ['#749c56', 200, false, true, false, false, '#4e6d63', 'stands'],
  'las-vegas': ['#a6977c', 30, false, true, false, true, '#45494b', 'sphere'],
  lusail: ['#c7b68a', 30, false, false, false, true, '#438986', 'stands'],
  madring: ['#ab9d7a', 80, false, true, false, false, '#77766c', 'stadium'],
  melbourne: ['#839961', 350, false, false, true, false, '#5b8270', 'stands'],
  'mexico-city': ['#7e8c59', 180, false, true, false, false, '#626163', 'stadium'],
  miami: ['#93aa65', 120, false, true, true, false, '#508d9e', 'stadium'],
  monaco: ['#a6aa8d', 50, false, true, true, false, '#737875', 'hotel'],
  montreal: ['#688b51', 550, false, false, true, false, '#a9a38a', 'stands'],
  monza: ['#75934c', 800, false, false, false, false, '#baad92', 'stands'],
  sepang: ['#6c984d', 400, false, false, false, false, '#b9ae94', 'wing'],
  shanghai: ['#8f9d69', 200, false, false, true, false, '#728879', 'wing'],
  silverstone: ['#909b66', 130, false, false, false, false, '#a89f89', 'wing'],
  singapore: ['#658b56', 190, false, true, true, true, '#50565a', 'wheel'],
  spa: ['#668349', 900, true, false, false, false, '#b1a68b', 'stands'],
  spielberg: ['#71964d', 700, true, false, false, false, '#b2a58b', 'stands'],
  suzuka: ['#7e9b58', 400, false, false, false, false, '#a6a38a', 'wheel'],
  'yas-marina': ['#c3b38e', 65, false, true, true, true, '#458b9c', 'hotel'],
  zandvoort: ['#b9b087', 90, false, false, false, false, '#c8b895', 'dunes'],
};

export function sceneryProfile(id: string): SceneryProfile {
  const row = profiles[id] ?? profiles['silverstone'];
  if (!row) {
    throw new Error('Circuit scenery is unavailable');
  }
  const [terrain, trees, conifers, urban, water, night, runoff, landmark] = row;
  return { terrain, trees, conifers, urban, water, night, runoff, landmark };
}
