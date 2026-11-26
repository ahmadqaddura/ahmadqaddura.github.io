(function () {
    const API_BASE = "https://cartoon-stats.ahmadqaddura01.workers.dev";
    const LIKED_KEY = "aq_liked_cartoons_v1";
    const SHARED_SESSION_KEY = "aq_shared_session_v1";

    let statsMap = {};
    let loaded = false;
    let loadPromise = null;
    const pendingLikes = new Set();

    function getLikedSet() {
        try {
            const raw = localStorage.getItem(LIKED_KEY);
            const arr = raw ? JSON.parse(raw) : [];
            return new Set(Array.isArray(arr) ? arr : []);
        } catch (_) {
            return new Set();
        }
    }

    function saveLikedSet(set) {
        try {
            localStorage.setItem(LIKED_KEY, JSON.stringify(Array.from(set)));
        } catch (_) {}
    }

    function getSharedSessionSet() {
        try {
            const raw = sessionStorage.getItem(SHARED_SESSION_KEY);
            const arr = raw ? JSON.parse(raw) : [];
            return new Set(Array.isArray(arr) ? arr : []);
        } catch (_) {
            return new Set();
        }
    }

    function saveSharedSessionSet(set) {
        try {
            sessionStorage.setItem(SHARED_SESSION_KEY, JSON.stringify(Array.from(set)));
        } catch (_) {}
    }

    function formatCount(n) {
        const num = Number(n) || 0;
        if (num <= 0) return "";
        if (num >= 1000) return (num / 1000).toFixed(num >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k";
        return String(num);
    }

    function getCounts(slug) {
        const entry = statsMap[slug];
        return {
            likes: (entry && Number(entry.likes)) || 0,
            shares: (entry && Number(entry.shares)) || 0,
        };
    }

    function updateSlugUI(slug, root) {
        const scope = root || document;
        const liked = getLikedSet().has(slug);
        const { likes, shares } = getCounts(slug);
        const likesText = formatCount(likes);
        const sharesText = formatCount(shares);

        scope.querySelectorAll(`[data-like-slug="${CSS.escape(slug)}"]`).forEach(btn => {
            btn.classList.toggle("is-liked", liked);
            btn.setAttribute("aria-pressed", liked ? "true" : "false");
            btn.setAttribute("title", liked ? "Unlike cartoon" : "Like cartoon");
        });

        scope.querySelectorAll(`[data-like-count="${CSS.escape(slug)}"]`).forEach(el => {
            el.textContent = likesText;
            el.classList.toggle("has-count", Boolean(likesText));
        });

        scope.querySelectorAll(`[data-share-count="${CSS.escape(slug)}"]`).forEach(el => {
            if (el.classList.contains("share-total-badge")) {
                el.textContent = sharesText ? ` (${sharesText})` : "";
            } else {
                el.textContent = sharesText;
            }
            el.classList.toggle("has-count", Boolean(sharesText));
        });
    }

    function sync(root) {
        const scope = root || document;
        const slugs = new Set();
        scope.querySelectorAll("[data-like-slug], [data-like-count], [data-share-count]").forEach(el => {
            const s = el.getAttribute("data-like-slug") || el.getAttribute("data-like-count") || el.getAttribute("data-share-count");
            if (s) slugs.add(s);
        });
        slugs.forEach(slug => updateSlugUI(slug, scope));
    }

    function load() {
        if (loaded) {
            sync(document);
            return Promise.resolve(statsMap);
        }
        if (loadPromise) return loadPromise;

        loadPromise = fetch(`${API_BASE}/stats`, { cache: "no-store" })
            .then(res => (res.ok ? res.json() : {}))
            .then(data => {
                if (data && typeof data === "object") {
                    statsMap = data;
                }
                loaded = true;
                sync(document);
                return statsMap;
            })
            .catch(() => {
                loaded = true;
                sync(document);
                return statsMap;
            });

        return loadPromise;
    }

    async function toggleLike(slug) {
        if (!slug || pendingLikes.has(slug)) return;
        pendingLikes.add(slug);

        const likedSet = getLikedSet();
        const wasLiked = likedSet.has(slug);
        const delta = wasLiked ? -1 : 1;
        const prev = getCounts(slug);

        // Optimistic update
        if (wasLiked) likedSet.delete(slug);
        else likedSet.add(slug);
        saveLikedSet(likedSet);

        statsMap[slug] = {
            likes: Math.max(0, prev.likes + delta),
            shares: prev.shares,
        };
        updateSlugUI(slug, document);

        if (!wasLiked) {
            document.querySelectorAll(`[data-like-slug="${CSS.escape(slug)}"]`).forEach(btn => {
                btn.classList.remove("pop");
                void btn.offsetWidth;
                btn.classList.add("pop");
            });
        }

        try {
            const res = await fetch(`${API_BASE}/like`, {
                method: "POST",
                headers: { "Content-Type": "text/plain" },
                body: JSON.stringify({ slug, delta }),
            });
            if (!res.ok) throw new Error("Like request failed");
            const data = await res.json();
            if (typeof data.likes === "number") {
                statsMap[slug] = {
                    likes: data.likes,
                    shares: typeof data.shares === "number" ? data.shares : prev.shares,
                };
                updateSlugUI(slug, document);
            }
        } catch (_) {
            // Rollback on failure
            if (wasLiked) likedSet.add(slug);
            else likedSet.delete(slug);
            saveLikedSet(likedSet);
            statsMap[slug] = prev;
            updateSlugUI(slug, document);
        } finally {
            pendingLikes.delete(slug);
        }
    }

    function recordShare(slug, channel) {
        if (!slug) return;
        const key = `${slug}::${channel || "any"}`;
        const sharedSet = getSharedSessionSet();
        if (sharedSet.has(key)) return;
        sharedSet.add(key);
        saveSharedSessionSet(sharedSet);

        const prev = getCounts(slug);
        statsMap[slug] = {
            likes: prev.likes,
            shares: prev.shares + 1,
        };
        updateSlugUI(slug, document);

        fetch(`${API_BASE}/share`, {
            method: "POST",
            keepalive: true,
            headers: { "Content-Type": "text/plain" },
            body: JSON.stringify({ slug }),
        })
            .then(res => (res.ok ? res.json() : null))
            .then(data => {
                if (data && typeof data.shares === "number") {
                    statsMap[slug] = {
                        likes: typeof data.likes === "number" ? data.likes : statsMap[slug].likes,
                        shares: data.shares,
                    };
                    updateSlugUI(slug, document);
                }
            })
            .catch(() => {});
    }

    function copyText(text, cb) {
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(cb).catch(() => fallbackCopy(text, cb));
        } else {
            fallbackCopy(text, cb);
        }
    }

    function fallbackCopy(text, cb) {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        try { if (document.execCommand("copy")) cb(); } catch (_) {}
        document.body.removeChild(ta);
    }

    function quickShare(btn) {
        const slug = btn.getAttribute("data-share-slug");
        const title = btn.getAttribute("data-share-title") || "Cartoon by Ahmad Qaddura";
        const url = btn.getAttribute("data-share-url") || location.href;

        if (navigator.share) {
            navigator.share({ title, url })
                .then(() => recordShare(slug, "native-card"))
                .catch(() => {});
            return;
        }

        copyText(url, () => {
            recordShare(slug, "copy-card");
            btn.classList.add("copied-tip");
            setTimeout(() => btn.classList.remove("copied-tip"), 1800);
        });
    }

    // Event delegation across all static and dynamically rendered cards/buttons
    document.addEventListener("click", (e) => {
        const likeBtn = e.target.closest("[data-like-slug]");
        if (likeBtn) {
            e.preventDefault();
            e.stopPropagation();
            toggleLike(likeBtn.getAttribute("data-like-slug"));
            return;
        }

        const quickShareBtn = e.target.closest("[data-share-slug]");
        if (quickShareBtn) {
            e.preventDefault();
            e.stopPropagation();
            quickShare(quickShareBtn);
            return;
        }

        const trackShareEl = e.target.closest("[data-share-track]");
        if (trackShareEl) {
            const slug = trackShareEl.getAttribute("data-share-track");
            const channel = trackShareEl.getAttribute("data-share-channel") || "link";
            recordShare(slug, channel);
        }
    });

    window.CartoonStats = {
        load,
        sync,
        toggleLike,
        recordShare,
        heartSvg: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>',
        shareSvg: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>',
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", load);
    } else {
        load();
    }
})();
