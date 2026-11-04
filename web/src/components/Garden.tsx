import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

// Original procedural artwork. No third-party scene bundles or textures.
export default function Garden({ paused, hovering }: { paused: boolean; hovering: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const state = useRef({ paused, hovering });
  const [ready, setReady] = useState(false);
  useEffect(() => { state.current = { paused, hovering }; }, [paused, hovering]);
  useEffect(() => {
    const host = container.current!;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: 'low-power' }); }
    catch { setReady(true); return; }
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(52, 1, .1, 120);
    camera.position.set(0, 3.3, 8);
    const mobile = window.innerWidth < 820;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, mobile ? 1.25 : 1.5));
    renderer.setClearColor(0x080907, 1);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    host.appendChild(renderer.domElement);
    const composer = new EffectComposer(renderer);
    // Soft bloom can render below device resolution; avoid heavy full-DPR passes.
    composer.setPixelRatio(mobile ? .65 : .85);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), .65, .6, .6);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    let seed = 99142;
    const random = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    const count = mobile ? 5200 : 11000;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const kinds = new Float32Array(count);
    const stems: number[] = [];
    const palette = ['#ead7b4', '#f3e6d1', '#cfb58a', '#bca881', '#b5b49a', '#e7ddc5', '#959b81'].map(c => new THREE.Color(c));
    for (let i = 0; i < count; i++) {
      const z = 9 - random() * 100;
      const side = random() > .5 ? 1 : -1;
      const path = 1.2 + .48 * Math.sin(z * .16);
      const x = side * (path + Math.pow(random(), .78) * 24);
      const hill = Math.pow(Math.abs(x) * .14, 1.55) + .65 * Math.sin(z * .11 + x * .18);
      const height = .12 + random() * .85;
      positions.set([x, hill + height - 1.4, z], i * 3);
      const color = palette[Math.floor(random() * palette.length)].clone();
      const isLeaf = random() < .43;
      if (isLeaf) color.set('#62674c').multiplyScalar(.25 + random() * .55);
      else color.multiplyScalar(.48 + random() * .9);
      colors.set([color.r, color.g, color.b], i * 3);
      sizes[i] = (isLeaf ? 16 : 21) + random() * (isLeaf ? 21 : 39);
      kinds[i] = isLeaf ? 0 : 1 + Math.floor(random() * 3);
      if (i % 2 === 0) stems.push(x, hill - 1.5, z, x, hill + height - 1.4, z);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geometry.setAttribute('aKind', new THREE.BufferAttribute(kinds, 1));
    const uniforms = { uTime: { value: 0 }, uTravel: { value: 0 }, uMouse: { value: new THREE.Vector2(3, 3) }, uHover: { value: 0 }, uRatio: { value: renderer.getPixelRatio() } };
    // Recycle flowers behind the camera into the distant fog, with no camera reset.
    const travel = 'p.z = mod(p.z + uTravel + 91.0, 100.0) - 91.0;';
    const material = new THREE.ShaderMaterial({
      uniforms, vertexColors: true, transparent: true, depthWrite: false,
      vertexShader: `
        attribute float aSize; attribute float aKind;
        uniform float uTime; uniform float uTravel; uniform float uHover; uniform float uRatio; uniform vec2 uMouse;
        varying vec3 vColor; varying float vKind; varying float vFog; varying float vGlow;
        void main() {
          vec3 p = position;
          ${travel}
          p.x += sin(uTime * .32 + p.z * .35 + p.y) * .075;
          p.y += sin(uTime * .4 + p.x) * .035;
          p.x += sign(p.x) * uHover * (.3 + abs(p.z) * .035);
          p.y += uHover * (.2 + sin(p.z + p.x) * .15);
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vec4 clip = projectionMatrix * mv;
          vec2 difference = clip.xy / clip.w - uMouse;
          float influence = exp(-dot(difference, difference) * 18.0);
          clip.xy += difference * influence * .11 * clip.w;
          gl_Position = clip;
          gl_PointSize = clamp(aSize * uRatio * (7.0 / -mv.z), 1.0, 155.0);
          vColor = color; vKind = aKind; vGlow = influence;
          vFog = 1.0 - smoothstep(8.0, 94.0, -mv.z);
        }`,
      fragmentShader: `
        varying vec3 vColor; varying float vKind; varying float vFog; varying float vGlow;
        void main() {
          vec2 p = gl_PointCoord - .5;
          float r = length(p); float a = atan(p.y, p.x);
          float alpha; vec3 c = vColor;
          if (vKind < .5) {
            vec2 q = vec2(p.x * .85 + p.y * .5, -p.x * .5 + p.y * .85);
            float leaf = pow(q.x / .21, 2.0) + pow(q.y / .47, 2.0);
            alpha = (1.0 - smoothstep(.7, 1.0, leaf)) * .65;
            c *= .7 + .3 * (1.0 - abs(q.x) * 4.0);
          } else {
            float petals = vKind < 1.5 ? 5.0 : vKind < 2.5 ? 8.0 : 6.0;
            float edge = .31 + .12 * cos(a * petals + vKind * 2.0);
            alpha = 1.0 - smoothstep(edge - .035, edge, r);
            float fold = .55 + .45 * pow(abs(cos(a * petals * .5 + vKind)), 2.0);
            c *= fold * (1.0 + r * .7);
            c = mix(c, vec3(.75, .48, .13), 1.0 - smoothstep(.065, .11, r));
            c += vec3(.55, .4, .2) * (1.0 - smoothstep(.0, .035, r));
          }
          if (alpha < .02) discard;
          c *= vFog * (1.0 + vGlow * .45);
          gl_FragColor = vec4(c, alpha * min(vFog * 1.8, 1.0));
        }`,
    });
    const flowers = new THREE.Points(geometry, material);
    scene.add(flowers);
    const stemGeometry = new THREE.BufferGeometry();
    stemGeometry.setAttribute('position', new THREE.Float32BufferAttribute(stems, 3));
    const stemMaterial = new THREE.ShaderMaterial({
      uniforms: { uTravel: uniforms.uTravel, uColor: { value: new THREE.Color('#575940') } },
      transparent: true, depthWrite: false,
      vertexShader: `
        uniform float uTravel; varying float vFog;
        void main() {
          vec3 p = position;
          ${travel}
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          vFog = 1.0 - smoothstep(8.0, 94.0, -mv.z);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `
        uniform vec3 uColor; varying float vFog;
        void main() { gl_FragColor = vec4(uColor, .22 * vFog); }`,
    });
    scene.add(new THREE.LineSegments(stemGeometry, stemMaterial));
    const dustGeometry = new THREE.BufferGeometry();
    const dust: number[] = [];
    for (let i = 0; i < 220; i++) dust.push((random() - .5) * 48, random() * 14 - 1, -random() * 75);
    dustGeometry.setAttribute('position', new THREE.Float32BufferAttribute(dust, 3));
    const dustMaterial = new THREE.PointsMaterial({ color: '#d7c5a4', size: .025, transparent: true, opacity: .35 });
    const particles = new THREE.Points(dustGeometry, dustMaterial); scene.add(particles);
    let width = 1, height = 1, visible = true, pausedRendered = false;
    const resize = () => {
      width = host.clientWidth; height = host.clientHeight;
      camera.aspect = width / height; camera.updateProjectionMatrix();
      renderer.setSize(width, height); composer.setSize(width, height);
      pausedRendered = false;
    };
    resize();
    const observer = new ResizeObserver(resize); observer.observe(host);
    const intersection = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; }); intersection.observe(host);
    const mouse = new THREE.Vector2(0, 0);
    const onMove = (event: PointerEvent) => { const rect = host.getBoundingClientRect(); mouse.set((event.clientX - rect.left) / width * 2 - 1, -((event.clientY - rect.top) / height * 2 - 1)); uniforms.uMouse.value.copy(mouse); };
    const onLeave = () => { mouse.set(0, 0); uniforms.uMouse.value.set(3, 3); };
    window.addEventListener('pointermove', onMove, { passive: true }); document.addEventListener('pointerleave', onLeave);
    let frame = 0, time = 0, last = 0;
    const animate = (now: number) => {
      frame = requestAnimationFrame(animate);
      if (!visible || document.hidden) return;
      if (state.current.paused && pausedRendered) return;
      if (now - last < 1000 / 30) return;
      const delta = Math.min((now - last) / 1000, .05); last = now;
      pausedRendered = state.current.paused;
      if (!state.current.paused) time += delta;
      uniforms.uTime.value = time;
      uniforms.uTravel.value = time * .6;
      uniforms.uHover.value += ((state.current.hovering && !state.current.paused ? 1 : 0) - uniforms.uHover.value) * .025;
      if (!state.current.paused) {
        camera.position.x += (mouse.x * .18 - camera.position.x) * .025;
        camera.position.y = 3.3 + Math.sin(time * .1) * .06;
        camera.position.z = 8 - Math.min(window.scrollY / height, 1) * .65;
      }
      camera.lookAt(0, 1.5, -26);
      particles.rotation.y = time * .004;
      composer.render();
    };
    frame = requestAnimationFrame(animate); setReady(true);
    return () => {
      cancelAnimationFrame(frame); observer.disconnect(); intersection.disconnect();
      window.removeEventListener('pointermove', onMove); document.removeEventListener('pointerleave', onLeave);
      geometry.dispose(); material.dispose(); stemGeometry.dispose(); stemMaterial.dispose(); dustGeometry.dispose(); dustMaterial.dispose();
      bloom.dispose(); composer.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
  }, []);
  return <div className={`garden ${ready ? 'garden-ready' : ''}`} ref={container} aria-hidden="true"><div className="garden-fallback" /><div className="garden-shade" /></div>;
}
