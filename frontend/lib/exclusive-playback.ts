/** Only one take plays at a time: starting one pauses the one that was playing. */
let current: HTMLAudioElement | null = null;

export function claimPlayback(el: HTMLAudioElement): void {
  if (current && current !== el) current.pause();
  current = el;
}

export function releasePlayback(el: HTMLAudioElement): void {
  if (current === el) current = null;
}
