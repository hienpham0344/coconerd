import { useEffect, useRef, useState } from 'react';

export function useAmbience() {
  const audio = useRef<{ context: AudioContext; gain: GainNode; filter: BiquadFilterNode; sources: AudioScheduledSourceNode[] } | null>(null);
  const mounted = useRef(true);
  const playingRef = useRef(false);
  const busyRef = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState('');
  const toggle = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    try {
      if (!audio.current) {
        const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (!AudioCtx) throw new Error('AudioContext unsupported');
        const context = new AudioCtx();
        const gain = context.createGain(); gain.gain.value = 0; gain.connect(context.destination);
        const filter = context.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = 650; filter.connect(gain);
        const buffer = context.createBuffer(1, context.sampleRate * 5, context.sampleRate);
        const data = buffer.getChannelData(0); let previous = 0;
        for (let i = 0; i < data.length; i++) { previous = (previous + (Math.random() * 2 - 1) * .02) / 1.02; data[i] = previous * 2; }
        const noise = context.createBufferSource(); noise.buffer = buffer; noise.loop = true; noise.connect(filter); noise.start();
        const sources: AudioScheduledSourceNode[] = [noise];
        for (const frequency of [130.81, 196, 261.63]) {
          const oscillator = context.createOscillator(); oscillator.frequency.value = frequency;
          const level = context.createGain(); level.gain.value = .035;
          oscillator.connect(level); level.connect(filter); oscillator.start();
          sources.push(oscillator);
        }
        audio.current = { context, gain, filter, sources };
      }
      await audio.current.context.resume();
      const current = audio.current;
      if (!mounted.current || !current) return;
      const next = !playingRef.current;
      current.gain.gain.setTargetAtTime(next ? .2 : 0, current.context.currentTime, .5);
      playingRef.current = next;
      setPlaying(next); setError('');
    } catch {
      if (mounted.current) setError('Trình duyệt chưa cho phép phát âm thanh.');
    } finally {
      busyRef.current = false;
    }
  };
  const muffle = (value: boolean) => { const a = audio.current; if (a && a.context.state === 'running') a.filter.frequency.setTargetAtTime(value ? 180 : 650, a.context.currentTime, .6); };
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      playingRef.current = false;
      const current = audio.current;
      audio.current = null;
      if (!current) return;
      for (const source of current.sources) {
        try { source.stop(); source.disconnect(); } catch { /* Already stopped */ }
      }
      try { current.filter.disconnect(); current.gain.disconnect(); } catch { /* Ignore */ }
      void current.context.close().catch(() => {});
    };
  }, []);
  return { playing, toggle, muffle, error };
}
