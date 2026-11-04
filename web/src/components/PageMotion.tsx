import { useEffect, useRef, type ReactNode } from 'react';
import { useReducedMotion } from '../hooks/useReducedMotion';

const revealTargets = [
  '.section-index', '.story-grid > *', '.process-heading', '.process-steps > article',
  '.landing-links > div', '.closing-section > :not(svg)', '.public-intro',
  '.feature-story > *', '.public-next', '.help-steps > article',
  '.help-faq-heading', '.public-faq > details', '.help-contact-grid > article',
  '.privacy-article > section', '.welcome-garden', '.stats-grid', '.topics-section',
].join(',');

export function PageMotion({ route, children }: { route: string; children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = root.current;
    if (!node || reduced) return;
    const arrival = node.animate([{ opacity: .2 }, { opacity: 1 }], {
      duration: 420, easing: 'ease-out',
    });
    return () => arrival.cancel();
  }, [route, reduced]);

  useEffect(() => {
    const node = root.current;
    if (!node || reduced || !('IntersectionObserver' in window)) return;
    const tracked = new Set<HTMLElement>();
    const reveal = (element: HTMLElement) => {
      element.classList.add('is-revealed');
      observer.unobserve(element);
    };
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) reveal(entry.target as HTMLElement);
      }
    }, { threshold: .08, rootMargin: '0px 0px -24px 0px' });
    const register = () => {
      node.querySelectorAll<HTMLElement>(revealTargets).forEach((element, index) => {
        if (tracked.has(element)) return;
        tracked.add(element);
        element.classList.add('scroll-reveal');
        element.style.setProperty('--reveal-delay', `${index % 3 * 65}ms`);
        observer.observe(element);
      });
    };
    register();
    // Lazy pages and filtered cards can arrive after the route has rendered.
    const mutations = new MutationObserver(register);
    mutations.observe(node, { childList: true, subtree: true });
    const focus = (event: FocusEvent) => {
      if (!(event.target instanceof Element)) return;
      const element = event.target.closest<HTMLElement>('.scroll-reveal');
      if (element) reveal(element);
    };
    node.addEventListener('focusin', focus);
    return () => {
      observer.disconnect();
      mutations.disconnect();
      node.removeEventListener('focusin', focus);
      tracked.forEach(element => {
        element.classList.remove('scroll-reveal', 'is-revealed');
        element.style.removeProperty('--reveal-delay');
      });
    };
  }, [route, reduced]);

  return <div ref={root} className="page-motion">{children}</div>;
}
