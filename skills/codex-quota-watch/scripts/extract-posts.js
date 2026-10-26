(() => {
  const capturedAt = new Date().toISOString();
  const posts = [];
  const warnings = [];
  const seen = new Set();
  const articles = Array.from(document.querySelectorAll("article"));

  const warn = (index, reason) => warnings.push(`article ${index + 1}: ${reason}`);
  const isInsideLinkedCard = (element, article) => {
    let ancestor = element.parentElement;
    while (ancestor && ancestor !== article) {
      if (ancestor.matches('[role="link"]') && ancestor.tagName.toLowerCase() !== "a") return true;
      ancestor = ancestor.parentElement;
    }
    return false;
  };
  const articleNodes = (article, selector) =>
    Array.from(article.querySelectorAll(selector)).filter((element) => !isInsideLinkedCard(element, article));
  const isShowMore = (article) =>
    Array.from(article.querySelectorAll("button, [role='button'], a"))
      .filter((element) => !isInsideLinkedCard(element, article))
      .some((element) => {
        const testId = element.getAttribute("data-testid") || "";
        const label = `${element.getAttribute("aria-label") || ""} ${element.getAttribute("title") || ""} ${element.textContent || ""}`;
        return /show[-\s]?more/i.test(testId) || /show\s+more|see\s+more|显示更多/i.test(label);
      });

  articles.forEach((article, index) => {
    // Ignore linked quote cards, then use only the first outer time and its closest link.
    const timeNodes = articleNodes(article, "time");
    const firstTime = timeNodes[0];
    const outerLink = firstTime && firstTime.closest("a[href]");
    if (!outerLink) return;

    let parsedUrl;
    try {
      parsedUrl = new URL(outerLink.getAttribute("href"), document.URL);
    } catch {
      return;
    }
    if (!new Set(["x.com", "www.x.com"]).has(parsedUrl.hostname.toLowerCase())) return;
    const match = parsedUrl.pathname.match(/^\/thsottiaux\/status\/(\d+)\/?$/);
    if (!match) return;

    const id = match[1];
    if (seen.has(id)) return;
    const canonicalUrl = `https://x.com/thsottiaux/status/${id}`;

    const textNodes = articleNodes(article, '[data-testid="tweetText"]');
    const nestedArticles = articleNodes(article, "article");
    if (timeNodes.length !== 1 || textNodes.length !== 1 || nestedArticles.length) {
      warn(index, "nested or quoted post content is ambiguous; skipped");
      return;
    }
    const socialContext = articleNodes(article, '[data-testid="socialContext"]')[0];
    if (socialContext && /reposted|retweeted|转发|转推/i.test(socialContext.textContent || "")) {
      warn(index, "repost content is not treated as the author's own post; skipped");
      return;
    }
    if (isShowMore(article)) {
      warn(index, "post has a Show more control and may be truncated; skipped");
      return;
    }

    const createdAt = (firstTime.getAttribute("datetime") || "").trim();
    if (!createdAt || !Number.isFinite(Date.parse(createdAt))) {
      warn(index, "missing or invalid time datetime; skipped");
      return;
    }
    const text = (textNodes[0].textContent || "").replace(/\s+/gu, " ").trim();
    if (!text) {
      warn(index, "tweetText is empty; skipped");
      return;
    }

    seen.add(id);
    posts.push({ id, author: "thsottiaux", text, created_at: createdAt, url: canonicalUrl });
  });

  posts.sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
  if (!posts.length && !warnings.length) warnings.push("No eligible thsottiaux posts were found in the currently loaded DOM.");
  return { schema_version: 1, captured_at: capturedAt, posts, warnings };
})()
