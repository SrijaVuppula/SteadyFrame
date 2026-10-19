// The deployed test clips (service/samples.py): a short name and a two-word tag for the picker.
// The picker draws each one as a still thumbnail; nothing is played.
export const CLIP_COPY: Record<string, [string, string]> = {
  sample_strobe_region: ['Flashing box', 'one region'],
  sample_red_strobe: ['Red strobe', 'saturated red'],
  sample_red_fullscreen: ['Full-screen red', 'asks you'],
  sample_clean: ['Calm clip', 'the control'],
};

export const FALLBACK = Object.keys(CLIP_COPY);

export function clipName(id: string): string {
  return CLIP_COPY[id]?.[0] ?? id;
}
