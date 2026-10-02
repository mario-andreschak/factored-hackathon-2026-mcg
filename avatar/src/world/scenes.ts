import type { Locale } from '../locale';

export const SCENES = [
  { id: 'pond-sanctuary', name: 'El santuario de aguas tranquilas', place: 'Donde el bosque escucha', image: '/scenes/01-pond-sanctuary.webp', weather: 'fireflies', tint: '#8ce4d1' },
  { id: 'lantern-grove', name: 'El bosque de los faroles', place: 'Un poco de luz para el siguiente paso', image: '/scenes/02-lantern-grove.webp', weather: 'fireflies', tint: '#edca85' },
  { id: 'rainy-canopy', name: 'Bajo la lluvia', place: 'Aquí no hay prisa', image: '/scenes/03-rainy-canopy.webp', weather: 'rain', tint: '#96b8d6' },
  { id: 'cliff-sunrise', name: 'Un horizonte distinto', place: 'Hay espacio para ver las cosas de otra manera', image: '/scenes/04-cliff-sunrise.webp', weather: 'pollen', tint: '#f7d4b0' },
  { id: 'river-crossing', name: 'Una piedra a la vez', place: 'Podemos cruzar juntos', image: '/scenes/05-river-crossing.webp', weather: 'pollen', tint: '#a6d3c3' },
  { id: 'moonlit-lake', name: 'El reflejo de la luna', place: 'Una claridad más serena', image: '/scenes/06-moonlit-lake.webp', weather: 'fireflies', tint: '#aabcec' },
  { id: 'old-ruins', name: 'Lo que permanece', place: 'Las historias antiguas dejan espacio para las nuevas', image: '/scenes/07-old-ruins.webp', weather: 'pollen', tint: '#a9cbb1' },
  { id: 'meadow', name: 'La pradera abierta', place: 'Respira. Has recorrido un largo camino.', image: '/scenes/08-meadow.webp', weather: 'pollen', tint: '#e8dba0' },
  { id: 'floating-islands', name: 'Sobre las nubes', place: 'Hay posibilidades que vale la pena imaginar', image: '/scenes/09-floating-islands.webp', weather: 'pollen', tint: '#d2c5e7' },
  { id: 'homecoming-sunset', name: 'El camino a casa', place: 'Un regreso más ligero', image: '/scenes/10-homecoming-sunset.webp', weather: 'fireflies', tint: '#f0b280' },
] as const;

export type Scene = typeof SCENES[number];
export type SceneId = Scene['id'];
const portuguese: Record<SceneId, { name: string; place: string }> = {
  'pond-sanctuary': { name: 'O santuário das águas tranquilas', place: 'Onde a floresta escuta' },
  'lantern-grove': { name: 'O bosque dos lampiões', place: 'Um pouco de luz para o próximo passo' },
  'rainy-canopy': { name: 'Sob a chuva', place: 'Aqui não há pressa' },
  'cliff-sunrise': { name: 'Um horizonte diferente', place: 'Há espaço para enxergar de outro jeito' },
  'river-crossing': { name: 'Uma pedra de cada vez', place: 'Podemos atravessar juntos' },
  'moonlit-lake': { name: 'O reflexo da lua', place: 'Uma clareza mais serena' },
  'old-ruins': { name: 'O que permanece', place: 'Histórias antigas abrem espaço para novas histórias' },
  meadow: { name: 'O campo aberto', place: 'Respire. Você já percorreu um longo caminho.' },
  'floating-islands': { name: 'Acima das nuvens', place: 'Há possibilidades que vale a pena imaginar' },
  'homecoming-sunset': { name: 'O caminho de casa', place: 'Um pouco mais leve que antes' },
};

export function sceneCopy(scene: Scene, locale: Locale = 'es'): { name: string; place: string } {
  return locale === 'pt' ? portuguese[scene.id] : { name: scene.name, place: scene.place };
}

export function getScenes(locale: Locale = 'es') {
  return SCENES.map(scene => ({ ...scene, ...sceneCopy(scene, locale) }));
}

export const localizedScenes = getScenes;

export type WorldPhase = 'idle' | 'listening' | 'thinking' | 'speaking';
export type WorldProps = {
  locale?: Locale;
  avatar: 'moss' | 'orbit' | 'spark';
  sceneIndex: number;
  phase: WorldPhase;
  audioLevel: number;
  reducedMotion: boolean;
  pointer: { x: number; y: number };
};
