// The deployed test clips (service/samples.py), with the short names the demo cards use.
/** Short names for the cards; the API's own names and descriptions stay the reference. */
export const CLIP_COPY: Record<string, [string, string]> = {
  sample_strobe_region: ['Flashing box', '6 flashes a second in one region'],
  sample_red_strobe: ['Red strobe', 'saturated red flashing on the right'],
  sample_red_fullscreen: ['Full-screen red', 'hard case: may ask for your approval'],
  sample_clean: ['Calm clip', 'the control: nothing should be flagged'],
};
export const FALLBACK = Object.keys(CLIP_COPY);

export function clipName(id: string): string {
  return CLIP_COPY[id]?.[0] ?? id;
}
