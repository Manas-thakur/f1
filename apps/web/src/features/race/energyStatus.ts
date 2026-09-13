import type { RaceCar } from './types';

export function energyMode(car: RaceCar | undefined) {
  const power = car?.channels['electrical_power_w'];
  if (power === undefined) {return 'UNAVAILABLE';}
  if (power < -1000) {return 'RECHARGING';}
  if (car?.channels['boost_latched'] === 1) {return 'BOOST HELD';}
  if (car?.channels['boost_active'] === 1 && power > 1000) {return 'BOOST';}
  if (power > 1000) {return 'DEPLOYING';}
  return 'IDLE';
}
