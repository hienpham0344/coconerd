import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveNavigation } from '../src/routes.ts';

test('legacy help destinations resolve to one guide', () => {
  for (const path of ['/guide', '/faq', '/support', '/status', '/docs', '/docs/setup']) {
    assert.equal(resolveNavigation(`#${path}`).route, '/guide', path);
  }
  assert.equal(resolveNavigation('#/docs/privacy').route, '/privacy');
});

test('invitation overlays preserve the current page and its scroll', () => {
  for (const path of ['/invite', '/connect']) {
    assert.deepEqual(resolveNavigation(`#${path}`, '/demo/topics/new-website'), {
      route: '/demo/topics/new-website', inviteOpen: true, resetScroll: false,
    });
  }
  assert.equal(resolveNavigation('#/invite').route, '/');
});

test('closing an invitation returns to the same page without scrolling', () => {
  const overlay = resolveNavigation('#/invite', '/features');
  assert.deepEqual(resolveNavigation(`#${overlay.route}`, overlay.route), {
    route: '/features', inviteOpen: false, resetScroll: false,
  });
});

test('content navigation resets scroll only when the destination changes', () => {
  assert.equal(resolveNavigation('#/features', '/guide').resetScroll, true);
  assert.equal(resolveNavigation('#/faq', '/guide').resetScroll, false);
  assert.equal(resolveNavigation('#/', '/guide').resetScroll, true);
});

test('demo deep links and unknown destinations retain their content route', () => {
  assert.equal(resolveNavigation('#/app/topics/new-website').route, '/demo/topics/new-website');
  assert.equal(resolveNavigation('#/missing').route, '/missing');
  assert.equal(resolveNavigation('').route, '/');
});
