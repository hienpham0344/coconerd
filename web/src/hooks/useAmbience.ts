import { useEffect, useRef, useState } from 'react';

export function useAmbience() {
  const audio = useRef<{ context: AudioContext; gain: GainNode; filter: BiquadFilterNode } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState('');
  const toggle = async () => {
    try {
      if (!audio.current) {
        const context = new AudioContext();
        const gain = context.createGain(); gain.gain.value = 0; gain.connect(context.destination);
        const filter = context.createBiquadFilter(); filter.type = 'lowpass'; filter.frequency.value = 650; filter.connect(gain);
        const buffer = context.createBuffer(1, context.sampleRate * 5, context.sampleRate);
        const data = buffer.getChannelData(0); let previous = 0;
        for (let i = 0; i < data.length; i++) { previous = (previous + (Math.random() * 2 - 1) * .02) / 1.02; data[i] = previous * 2; }
        const noise = context.createBufferSource(); noise.buffer = buffer; noise.loop = true; noise.connect(filter); noise.start();
        for (const frequency of [130.81, 196, 261.63]) { const oscillator = context.createOscillator(); oscillator.frequency.value = frequency; const level = context.createGain(); level.gain.value = .035; oscillator.connect(level); level.connect(filter); oscillator.start(); }
        audio.current = { context, gain, filter };
      }
      await audio.current.context.resume();
      audio.current.gain.gain.setTargetAtTime(playing ? 0 : .2, audio.current.context.currentTime, .5);
      setPlaying(!playing); setError('');
    } catch { setError('Trình duyệt chưa cho phép phát âm thanh.'); }
  };
  const muffle = (value: boolean) => { const a = audio.current; if (a) a.filter.frequency.setTargetAtTime(value ? 180 : 650, a.context.currentTime, .6); };
  useEffect(() => () => { void audio.current?.context.close(); audio.current = null; }, []);
  return { playing, toggle, muffle, error };
}
