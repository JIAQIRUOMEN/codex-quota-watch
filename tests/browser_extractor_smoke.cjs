// Offline smoke tests for the browser-console extractor. Uses only Node's stdlib.
// Fixtures are synthetic; this does not connect to or claim to test X.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const sourcePath = path.join(root, 'skills', 'codex-quota-watch', 'scripts', 'extract-posts.js');
const source = fs.readFileSync(sourcePath, 'utf8');

class FakeElement {
  constructor(attributes = {}, text = '') {
    this.attributes = attributes;
    this.textContent = text;
    this.innerText = text;
    this.href = attributes.href || '';
    this.parentElement = null;
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  closest(selector) { return selector === 'a[href]' ? this.permalink || null : null; }
  matches(selector) { return selector.includes('role') && this.getAttribute('role') === 'link'; }
}

class FakeArticle extends FakeElement {
  constructor({ id, author = 'thsottiaux', text = 'Synthetic quota reset post', datetime, href, nested = [], quoted = [], showMore = false, extraTimes = [], withTime = true }) {
    super({}, text);
    this.times = [];
    const permalink = new FakeElement({ href: href || `https://x.com/${author}/status/${id}`, role: 'link' });
    permalink.tagName = 'A';
    permalink.parentElement = this;
    this.permalink = permalink;
    if (withTime) {
      const time = new FakeElement(datetime === undefined ? {} : { datetime });
      time.permalink = permalink;
      time.parentElement = permalink;
      this.times.push(time);
    }
    this.times.push(...extraTimes.map((time) => { time.parentElement = this; return time; }));
    this.tweetTexts = text === null ? [] : [new FakeElement({ 'data-testid': 'tweetText' }, text)];
    for (const quotedPost of quoted) {
      const quoteLink = new FakeElement({ role: 'link' });
      quoteLink.tagName = 'DIV';
      const quoteTime = new FakeElement(quotedPost.datetime === undefined ? {} : { datetime: quotedPost.datetime });
      quoteTime.permalink = new FakeElement({ href: quotedPost.href || `https://x.com/${quotedPost.author || 'someone_else'}/status/${quotedPost.id}` });
      quoteTime.parentElement = quoteLink;
      const quoteText = new FakeElement({ 'data-testid': 'tweetText' }, quotedPost.text || '');
      quoteText.parentElement = quoteLink;
      this.times.push(quoteTime);
      this.tweetTexts.push(quoteText);
    }
    for (const time of this.times) if (!time.parentElement) time.parentElement = this;
    for (const tweetText of this.tweetTexts) if (!tweetText.parentElement) tweetText.parentElement = this;
    this.nestedArticles = nested;
    this.showMoreNodes = showMore ? [new FakeElement({ 'data-testid': 'show-more' }, 'Show more')] : [];
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    if (selector === 'time' || /(^|[\s,])time(?:\b|\[)/.test(selector)) return this.times;
    if (selector.includes('tweetText')) return this.tweetTexts;
    if (selector.includes('article')) return this.nestedArticles;
    if (/show-more|show more|aria-label|button/i.test(selector)) return this.showMoreNodes;
    return [];
  }
}

function extract(articles) {
  const document = { querySelectorAll(selector) { return selector === 'article' ? articles : []; } };
  return vm.runInNewContext(source, { document, URL, Date, console: { log() {} } }, { timeout: 1000 });
}

function post(id, datetime, text = `Synthetic Codex quota reset ${id}`, extra = {}) {
  return new FakeArticle({ id, datetime, text, ...extra });
}

const valid = extract([post('42', '2026-10-26T09:00:00Z')]);
// X's ordinary timestamp anchor itself may carry role="link"; it is not a quote card.
assert.equal(valid.schema_version, 1);
assert.equal(valid.posts.length, 1);
assert.equal(valid.posts[0].author, 'thsottiaux');
assert.equal(valid.posts[0].id, '42');
assert.equal(valid.posts[0].url, 'https://x.com/thsottiaux/status/42');

const empty = extract([]);
assert.deepEqual(Array.from(empty.posts), []);

const invalid = extract([
  post('90', '2026-10-26T10:00:00Z', 'Synthetic post by another account', { author: 'someone_else' }),
  post('91', undefined, 'Synthetic post missing datetime'),
  post('92', '2026-10-26T10:00:00Z', 'Synthetic truncated post', { showMore: true }),
  post('93', '2026-10-26T10:00:00Z', 'Synthetic parent with quoted nested article', { nested: [post('999', '2026-10-26T09:59:00Z', 'Synthetic quoted author post', { author: 'someone_else' })] }),
]);
assert.deepEqual(Array.from(invalid.posts), []);
assert.ok(invalid.warnings.length >= 3, 'missing-time, truncated, and nested articles should be explained');

const outerOwnText = extract([
  post('300', '2026-10-26T10:00:00Z', 'ordinary', {
    quoted: [{ id: '301', author: 'someone_else', datetime: '2026-10-26T09:59:00Z', text: 'Codex quota reset is complete' }],
  }),
]);
assert.equal(outerOwnText.posts.length, 1);
assert.equal(outerOwnText.posts[0].text, 'ordinary', 'quoted reset text must not become the Tibo post body');

const quoteOnly = extract([
  post('302', '2026-10-26T10:01:00Z', null, {
    quoted: [{ id: '303', author: 'someone_else', datetime: '2026-10-26T10:00:00Z', text: 'Codex quota reset is complete' }],
  }),
]);
assert.deepEqual(Array.from(quoteOnly.posts), [], 'a quote alone is not an outer Tibo post');

const foreignOuterQuotesTibo = extract([
  post('304', '2026-10-26T10:02:00Z', 'foreign outer post', {
    author: 'someone_else',
    quoted: [{ id: '305', author: 'thsottiaux', datetime: '2026-10-26T10:01:00Z', text: 'Codex quota reset is complete' }],
  }),
]);
assert.deepEqual(Array.from(foreignOuterQuotesTibo.posts), [], 'a foreign outer post cannot be assigned to Tibo from its quote');

const ordered = extract([
  post('200', '2026-10-26T11:00:00Z', 'Synthetic later post'),
  post('100', '2026-10-26T09:00:00Z', 'Synthetic first version'),
  post('100', '2026-10-26T09:00:00Z', 'Synthetic duplicate with changed text'),
]);
assert.deepEqual(Array.from(ordered.posts, item => item.id), ['100', '200']);
assert.deepEqual(Array.from(ordered.posts, item => item.created_at), ['2026-10-26T09:00:00Z', '2026-10-26T11:00:00Z']);
assert.equal(ordered.posts[0].text, 'Synthetic first version', 'dedup must retain the first copy');

console.log('browser extractor fixture smoke: OK (synthetic DOM only)');
